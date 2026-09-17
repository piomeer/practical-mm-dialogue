#!/usr/bin/env python3
"""List format_pass samples in the review_queue (clue list; not a human-pass gate)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "实用多轮对话类图文数据集" / "samples"
PENDING = SAMPLES / "_pending_review"


def is_pending(data: dict) -> bool:
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    qs = meta.get("qa_status")
    if qs in {"human_pass", "rejected"}:
        return False
    if meta.get("review_queue") is True:
        return True
    return qs in {"format_pass", "auto_pass"}


def iter_sample_files(include_pending_dir: bool) -> list[Path]:
    files = sorted(SAMPLES.glob("practical_mm_dialogue_*.json"))
    if include_pending_dir and PENDING.is_dir():
        primary = {p.name for p in files}
        for p in sorted(PENDING.glob("practical_mm_dialogue_*.json")):
            if p.name not in primary:
                files.append(p)
    return files


def ocr_summary(meta: dict) -> dict:
    oc = meta.get("ocr_spotcheck")
    if not isinstance(oc, dict):
        return {"has_ocr_spotcheck": False}
    return {
        "has_ocr_spotcheck": True,
        "ocr_api_ok": oc.get("api_ok", oc.get("ok")),
        "ocr_verified": oc.get("verified", False),
        "ocr_merchant": oc.get("merchant_legal_name") or oc.get("merchant_or_title"),
        "ocr_header_person": oc.get("header_person_name"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="List format_pass samples (ocr spotcheck is clue only, not verified)"
    )
    parser.add_argument("--jsonl-out", type=Path, default=None)
    parser.add_argument(
        "--include-pending-dir-only-extras",
        action="store_true",
        help="also scan samples/_pending_review for ids not in samples/",
    )
    args = parser.parse_args()

    rows: list[dict] = []
    for path in iter_sample_files(args.include_pending_dir_only_extras):
        data = json.loads(path.read_text(encoding="utf-8"))
        if not is_pending(data):
            continue
        meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
        images = data.get("images") or []
        row = {
            "sample_id": data.get("sample_id"),
            "path": str(path.relative_to(ROOT)),
            "task_type": data.get("task_type"),
            "scenario": data.get("scenario"),
            "qa_status": meta.get("qa_status"),
            "review_queue": meta.get("review_queue"),
            "source_paths": meta.get("source_paths"),
            "image_paths": [im.get("image_path") for im in images if isinstance(im, dict)],
        }
        row.update(ocr_summary(meta))
        rows.append(row)

    print(f"format_pass_queue={len(rows)} (not human_pass; ocr verified always false if present)")
    for r in rows:
        if r.get("has_ocr_spotcheck"):
            ocr = (
                f"api_ok={r.get('ocr_api_ok')} verified={r.get('ocr_verified')} "
                f"merchant={r.get('ocr_merchant')!r}"
            )
        else:
            ocr = "ocr=none"
        print(
            f"{r['sample_id']}\t{r['task_type']}\tqa={r['qa_status']}\t{ocr}\t"
            f"src={r.get('source_paths')}\t{r['path']}"
        )

    out = args.jsonl_out or (PENDING / "queue.jsonl")
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
