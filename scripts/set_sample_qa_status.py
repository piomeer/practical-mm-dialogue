#!/usr/bin/env python3
"""Set sample meta.qa_status (e.g. human_pass) after manual QA."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "实用多轮对话类图文数据集" / "samples"
PENDING = SAMPLES / "_pending_review"
ALLOWED = {"format_pass", "human_pass", "rejected"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Promote/reject sample QA status")
    parser.add_argument("sample_id", help="e.g. practical_mm_dialogue_000010 or 10")
    parser.add_argument(
        "--status",
        required=True,
        choices=sorted(ALLOWED),
        help="new meta.qa_status",
    )
    args = parser.parse_args()

    sid = args.sample_id.strip()
    if sid.isdigit():
        sid = f"practical_mm_dialogue_{int(sid):06d}"
    path = SAMPLES / f"{sid}.json"
    if not path.is_file():
        print(f"missing {path}", file=sys.stderr)
        return 2

    data = json.loads(path.read_text(encoding="utf-8"))
    meta = data.setdefault("meta", {})
    meta["qa_status"] = args.status
    meta["review_queue"] = args.status == "format_pass"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    pending = PENDING / f"{sid}.json"
    if args.status == "human_pass" and pending.is_file():
        pending.unlink()
        print(f"removed pending mirror {pending.relative_to(ROOT)}")
    elif pending.is_file() or args.status == "format_pass":
        PENDING.mkdir(parents=True, exist_ok=True)
        pending.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")

    print(f"updated {path.relative_to(ROOT)} qa_status={args.status} review_queue={meta['review_queue']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
