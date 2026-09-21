#!/usr/bin/env python3
"""Rebuild image_inventory.jsonl: untouched / processed_unqualified / qualified."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "实用多轮对话类图文数据集" / "samples"
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
POOLS = ("data", "data_used", "data_lt720")
QUALIFIED = {"agent_pass", "human_pass"}


def load_nas_root() -> Path | None:
    env_path = ROOT / ".env"
    if env_path.is_file():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("NAS_ROOT=") and not line.startswith("#"):
                val = line.split("=", 1)[1].strip().strip('"').strip("'")
                if val:
                    p = Path(val)
                    return p if p.is_dir() else None
    env = os.environ.get("NAS_ROOT", "").strip()
    if env:
        p = Path(env)
        return p if p.is_dir() else None
    return None


def scan_pool(pool_dir: Path, pool: str) -> dict[str, dict]:
    found: dict[str, dict] = {}
    if not pool_dir.is_dir():
        return found
    for p in pool_dir.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in IMAGE_EXTS:
            continue
        if "_meta" in p.parts:
            continue
        rel = str(p.relative_to(pool_dir)).replace("\\", "/")
        found[rel] = {
            "rel_path": rel,
            "pool": pool,
            "local_cached": True,
            "nas_rel": f"cold/{pool}/{rel}",
            "bytes": p.stat().st_size,
        }
    return found


def scan_nas_cold(nas_root: Path, pool: str) -> dict[str, dict]:
    cold = nas_root / "cold" / pool
    found: dict[str, dict] = {}
    if not cold.is_dir():
        return found
    for p in cold.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in IMAGE_EXTS:
            continue
        rel = str(p.relative_to(cold)).replace("\\", "/")
        found[rel] = {
            "rel_path": rel,
            "pool": pool,
            "local_cached": False,
            "nas_rel": f"cold/{pool}/{rel}",
            "bytes": p.stat().st_size,
        }
    return found


def sample_index() -> dict[str, list[dict]]:
    """rel_path -> list of {sample_id, qa_status, agent_verdict}"""
    by: dict[str, list[dict]] = {}
    if not SAMPLES.is_dir():
        return by
    for jp in SAMPLES.glob("practical_mm_dialogue_*.json"):
        data = json.loads(jp.read_text(encoding="utf-8"))
        meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
        qs = meta.get("qa_status")
        aa = meta.get("agent_audit") if isinstance(meta.get("agent_audit"), dict) else {}
        info = {
            "sample_id": data.get("sample_id") or jp.stem,
            "qa_status": qs,
            "agent_verdict": aa.get("verdict"),
        }
        for sp in meta.get("source_paths") or []:
            if isinstance(sp, str) and "/" in sp:
                by.setdefault(sp, []).append(info)
        for im in data.get("images") or []:
            if not isinstance(im, dict):
                continue
            name = Path(im.get("image_path") or "").name
            if not name:
                continue
            # filename-only: attach under every matching source later; also store bare
            by.setdefault(f"__name__/{name}", []).append(info)
    return by


def process_status(links: list[dict]) -> tuple[str, str | None, str | None]:
    if not links:
        return "untouched", None, None
    # prefer qualified
    for L in links:
        if L.get("qa_status") in QUALIFIED:
            return "qualified", L.get("qa_status"), L.get("agent_verdict")
    # any sample counts as processed
    last = links[-1]
    return "processed_unqualified", last.get("qa_status"), last.get("agent_verdict")


def main() -> int:
    parser = argparse.ArgumentParser(description="Rebuild image_inventory.jsonl")
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "data" / "_meta" / "image_inventory.jsonl",
    )
    parser.add_argument("--also-nas-ledger", action="store_true")
    args = parser.parse_args()

    nas_root = load_nas_root()
    samples = sample_index()
    rows: dict[str, dict] = {}

    for pool in POOLS:
        local = scan_pool(ROOT / pool, pool)
        nas_map = scan_nas_cold(nas_root, pool) if nas_root else {}
        keys = set(local) | set(nas_map)
        for rel in keys:
            loc = local.get(rel)
            nas = nas_map.get(rel)
            base = loc or nas or {}
            entry = {
                "rel_path": rel,
                "pool": pool if (loc or nas) else None,
                "nas_rel": f"cold/{pool}/{rel}",
                "local_cached": bool(loc),
                "on_nas": bool(nas),
                "bytes": (loc or nas or {}).get("bytes"),
            }
            # merge key by pool+rel
            key = f"{pool}/{rel}"
            rows[key] = entry

    # attach sample links
    now = datetime.now(timezone.utc).isoformat()
    out_rows: list[dict] = []
    for key, entry in sorted(rows.items()):
        pool = entry["pool"]
        rel = entry["rel_path"]
        links = list(samples.get(rel) or [])
        # also match by filename
        name = Path(rel).name
        for extra in samples.get(f"__name__/{name}") or []:
            if extra not in links:
                links.append(extra)
        status, qs, verdict = process_status(links)
        entry.update(
            {
                "process_status": status,
                "sample_ids": [L["sample_id"] for L in links],
                "qa_status": qs,
                "agent_verdict": verdict,
                "updated_at": now,
            }
        )
        out_rows.append(entry)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as f:
        for r in out_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    from collections import Counter

    c = Counter(r["process_status"] for r in out_rows)
    print(f"wrote {args.out} rows={len(out_rows)} status={dict(c)}")

    if args.also_nas_ledger and nas_root:
        dest = nas_root / "ledger" / "image_inventory.jsonl"
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil_copy = args.out.read_text(encoding="utf-8")
            dest.write_text(shutil_copy, encoding="utf-8")
            print(f"also wrote {dest}")
        except OSError as e:
            print(f"warn: could not write NAS ledger: {e}", file=sys.stderr)

    # brief md next to jsonl
    md = args.out.with_suffix(".md")
    md.write_text(
        "# image_inventory summary\n\n"
        + "\n".join(f"- `{k}`: {v}" for k, v in sorted(c.items()))
        + f"\n\nTotal rows: {len(out_rows)}\n"
        + f"Updated: {now}\n",
        encoding="utf-8",
    )
    print(f"wrote {md}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
