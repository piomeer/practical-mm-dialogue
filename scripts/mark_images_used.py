#!/usr/bin/env python3
"""Move used images from data/ to data_used/ and mark meta rows used=true."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DATA_USED = ROOT / "data_used"
META_PATH = DATA / "_meta" / "index.jsonl"
SAMPLES_DIR = ROOT / "实用多轮对话类图文数据集" / "samples"
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
CATEGORIES = [
    "生活场景",
    "工作场景",
    "收据",
    "文档截图",
    "图表推理",
    "学习材料",
    "代码报错",
]


def read_meta_rows() -> list[dict]:
    if not META_PATH.exists():
        return []
    rows = []
    for line in META_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def write_meta_rows(rows: list[dict]) -> None:
    META_PATH.parent.mkdir(parents=True, exist_ok=True)
    with META_PATH.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def resolve_rel_path(path_arg: str) -> str | None:
    """Normalize to category/filename relative path under data/."""
    p = Path(path_arg)
    parts = p.parts
    if len(parts) >= 2 and parts[0] in CATEGORIES:
        return f"{parts[0]}/{parts[-1]}"
    # bare filename: search under data/
    name = p.name
    for cat in CATEGORIES:
        candidate = DATA / cat / name
        if candidate.is_file():
            return f"{cat}/{name}"
        used = DATA_USED / cat / name
        if used.is_file():
            return f"{cat}/{name}"
    return None


# Default archive gate: Agent 主审或人加签均可出库
MARKABLE_QA = {"agent_pass", "human_pass"}


def paths_from_samples(*, require_markable: bool = True) -> list[str]:
    found: list[str] = []
    if not SAMPLES_DIR.is_dir():
        print(f"samples dir missing: {SAMPLES_DIR}", file=sys.stderr)
        return found
    for jp in sorted(SAMPLES_DIR.glob("practical_mm_dialogue_*.json")):
        data = json.loads(jp.read_text(encoding="utf-8"))
        meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
        qs = meta.get("qa_status")
        if require_markable and qs not in MARKABLE_QA:
            print(
                f"skip {jp.name}: qa_status={qs!r} "
                f"(need agent_pass/human_pass; use --allow-format-pass to override)",
                file=sys.stderr,
            )
            continue
        for img in data.get("images") or []:
            ip = img.get("image_path") or ""
            name = Path(ip).name
            if not name:
                continue
            rel = resolve_rel_path(name)
            if rel:
                found.append(rel)
            else:
                print(f"warn: no data match for sample image {name} ({jp.name})", file=sys.stderr)
    # unique preserve order
    seen: set[str] = set()
    out: list[str] = []
    for r in found:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out


def mark_one(rel: str, rows: list[dict], dry_run: bool) -> str:
    src = DATA / rel
    dst = DATA_USED / rel

    if dst.is_file() and not src.is_file():
        # already archived; ensure meta flag
        updated = False
        for row in rows:
            if row.get("local_path") == rel and not row.get("used"):
                row["used"] = True
                updated = True
        return "already_used" + ("+meta" if updated else "")

    if not src.is_file():
        return "missing_in_data"

    dst.parent.mkdir(parents=True, exist_ok=True)
    if dry_run:
        return "would_move"

    if dst.exists():
        return "conflict_dest_exists"

    shutil.move(str(src), str(dst))
    matched = False
    for row in rows:
        if row.get("local_path") == rel:
            row["used"] = True
            matched = True
    if not matched:
        # file existed without meta row — still moved
        return "moved_no_meta"
    return "moved"


def main() -> int:
    parser = argparse.ArgumentParser(description="Move used images data/ → data_used/")
    parser.add_argument(
        "--paths",
        nargs="*",
        default=[],
        help="相对路径如 收据/0001mcdonalds收据.jpg，或仅文件名",
    )
    parser.add_argument(
        "--from-samples",
        action="store_true",
        help="从 samples/*.json 的 image_path 文件名匹配 data/ 并归档",
    )
    parser.add_argument(
        "--allow-format-pass",
        action="store_true",
        help="允许归档尚未 agent_pass/human_pass 的样本配图（默认需已主审通过）",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    rels: list[str] = []
    if args.from_samples:
        rels.extend(paths_from_samples(require_markable=not args.allow_format_pass))
    for p in args.paths:
        rel = resolve_rel_path(p)
        if not rel:
            print(f"无法解析路径: {p}", file=sys.stderr)
            return 2
        rels.append(rel)

    if not rels:
        if args.from_samples and not args.paths:
            print(
                "没有可归档路径：--from-samples 未找到 agent_pass/human_pass 样本"
                "（先 Agent 主审 apply_agent_audit，或加 --allow-format-pass）",
                file=sys.stderr,
            )
        else:
            print("请提供 --paths 或 --from-samples", file=sys.stderr)
        return 2

    # unique preserve order
    seen: set[str] = set()
    uniq: list[str] = []
    for r in rels:
        if r not in seen:
            seen.add(r)
            uniq.append(r)

    rows = read_meta_rows()
    counts: dict[str, int] = {}
    for rel in uniq:
        status = mark_one(rel, rows, dry_run=args.dry_run)
        counts[status] = counts.get(status, 0) + 1
        print(f"{status}: {rel}")

    if not args.dry_run:
        write_meta_rows(rows)

    print("summary:", ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    bad = counts.get("missing_in_data", 0) + counts.get("conflict_dest_exists", 0)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
