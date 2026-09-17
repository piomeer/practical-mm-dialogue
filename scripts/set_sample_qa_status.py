#!/usr/bin/env python3
"""Set sample meta.qa_status (agent_pass / human_pass / format_pass / rejected)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "实用多轮对话类图文数据集" / "samples"
PENDING = SAMPLES / "_pending_review"
ALLOWED = {"format_pass", "agent_pass", "human_pass", "rejected"}
# Statuses that leave the format_pass pending mirror
PROMOTED = {"agent_pass", "human_pass", "rejected"}


def normalize_sample_id(sample_id: str) -> str:
    sid = sample_id.strip()
    if sid.isdigit():
        return f"practical_mm_dialogue_{int(sid):06d}"
    return sid


def apply_status(
    path: Path,
    status: str,
    *,
    human_spot_queue: bool | None = None,
    agent_audit: dict | None = None,
) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    meta = data.setdefault("meta", {})
    meta["qa_status"] = status
    meta["review_queue"] = status == "format_pass"
    if human_spot_queue is not None:
        meta["human_spot_queue"] = human_spot_queue
    elif status in PROMOTED:
        meta["human_spot_queue"] = False
    if agent_audit is not None:
        meta["agent_audit"] = agent_audit
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    sid = path.stem
    pending = PENDING / f"{sid}.json"
    if status in PROMOTED and pending.is_file():
        pending.unlink()
    elif status == "format_pass":
        PENDING.mkdir(parents=True, exist_ok=True)
        pending.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    return meta


def main() -> int:
    parser = argparse.ArgumentParser(description="Promote/reject sample QA status")
    parser.add_argument("sample_id", help="e.g. practical_mm_dialogue_000010 or 10")
    parser.add_argument(
        "--status",
        required=True,
        choices=sorted(ALLOWED),
        help="new meta.qa_status",
    )
    parser.add_argument(
        "--human-spot-queue",
        action="store_true",
        help="set meta.human_spot_queue=true (for needs_human)",
    )
    args = parser.parse_args()

    sid = normalize_sample_id(args.sample_id)
    path = SAMPLES / f"{sid}.json"
    if not path.is_file():
        print(f"missing {path}", file=sys.stderr)
        return 2

    meta = apply_status(
        path,
        args.status,
        human_spot_queue=True if args.human_spot_queue else None,
    )
    pending = PENDING / f"{sid}.json"
    if args.status in PROMOTED and not pending.is_file():
        print(f"cleared pending mirror for {sid}")
    print(
        f"updated {path.relative_to(ROOT)} qa_status={args.status} "
        f"review_queue={meta['review_queue']} "
        f"human_spot_queue={meta.get('human_spot_queue')}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
