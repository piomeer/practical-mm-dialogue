#!/usr/bin/env python3
"""Apply structured Agent audit jsonl → qa_status agent_pass / format_pass / rejected."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from set_sample_qa_status import (  # noqa: E402
    SAMPLES,
    apply_status,
    normalize_sample_id,
)

ALLOWED_VERDICTS = {"pass", "fail", "needs_human"}


def load_rows(path: Path) -> list[dict]:
    rows: list[dict] = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as e:
            raise SystemExit(f"{path}:{i} invalid JSON: {e}") from e
        if not isinstance(row, dict):
            raise SystemExit(f"{path}:{i} row must be object")
        rows.append(row)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Apply agent audit jsonl (pass→agent_pass, fail/needs_human→format_pass)"
    )
    parser.add_argument("jsonl", type=Path, help="logs/agent_audit/<batch>.jsonl")
    parser.add_argument(
        "--reject-fails",
        action="store_true",
        help="set fail verdicts to rejected instead of leaving format_pass",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.jsonl.is_file():
        print(f"missing {args.jsonl}", file=sys.stderr)
        return 2

    rows = load_rows(args.jsonl)
    counts: dict[str, int] = {}
    now = datetime.now(timezone.utc).isoformat()

    for row in rows:
        sid_raw = row.get("sample_id")
        verdict = row.get("verdict")
        if not isinstance(sid_raw, str) or not sid_raw.strip():
            print(f"skip row without sample_id: {row!r}", file=sys.stderr)
            counts["bad_row"] = counts.get("bad_row", 0) + 1
            continue
        if verdict not in ALLOWED_VERDICTS:
            print(f"{sid_raw}: invalid verdict={verdict!r}", file=sys.stderr)
            counts["bad_verdict"] = counts.get("bad_verdict", 0) + 1
            continue

        sid = normalize_sample_id(sid_raw)
        path = SAMPLES / f"{sid}.json"
        if not path.is_file():
            print(f"missing sample {path}", file=sys.stderr)
            counts["missing"] = counts.get("missing", 0) + 1
            continue

        audit_meta = {
            "verdict": verdict,
            "task_type": row.get("task_type"),
            "reasons": row.get("reasons") or [],
            "critical_checks": row.get("critical_checks") or {},
            "batch_file": str(args.jsonl.relative_to(ROOT))
            if args.jsonl.is_absolute() and ROOT in args.jsonl.parents
            else str(args.jsonl),
            "applied_at": now,
        }

        if verdict == "pass":
            status = "agent_pass"
            spot = False
        elif verdict == "needs_human":
            status = "format_pass"
            spot = True
        else:  # fail
            status = "rejected" if args.reject_fails else "format_pass"
            spot = False

        if args.dry_run:
            print(f"dry-run {sid} → {status} human_spot_queue={spot} verdict={verdict}")
        else:
            apply_status(
                path,
                status,
                human_spot_queue=spot,
                agent_audit=audit_meta,
            )
            print(f"{sid} → {status} human_spot_queue={spot} verdict={verdict}")

        counts[verdict] = counts.get(verdict, 0) + 1

    print("summary:", ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
