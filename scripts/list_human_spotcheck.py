#!/usr/bin/env python3
"""List human spot-check queue: all needs_human + random sample of agent_pass."""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "实用多轮对话类图文数据集" / "samples"
PENDING = SAMPLES / "_pending_review"


def load_samples() -> list[tuple[Path, dict]]:
    out: list[tuple[Path, dict]] = []
    for path in sorted(SAMPLES.glob("practical_mm_dialogue_*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        out.append((path, data))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Human spot-check list (needs_human ∪ sample of agent_pass)"
    )
    parser.add_argument(
        "--sample-rate",
        type=float,
        default=0.1,
        help="fraction of agent_pass to include (default 0.1)",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--jsonl-out",
        type=Path,
        default=None,
        help="default: samples/_pending_review/human_spotcheck.jsonl",
    )
    args = parser.parse_args()
    if not 0.0 <= args.sample_rate <= 1.0:
        raise SystemExit("--sample-rate must be in [0, 1]")

    needs: list[dict] = []
    agent_pass: list[dict] = []

    for path, data in load_samples():
        meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
        qs = meta.get("qa_status")
        row = {
            "sample_id": data.get("sample_id"),
            "path": str(path.relative_to(ROOT)),
            "task_type": data.get("task_type"),
            "scenario": data.get("scenario"),
            "qa_status": qs,
            "human_spot_queue": bool(meta.get("human_spot_queue")),
            "agent_verdict": (meta.get("agent_audit") or {}).get("verdict")
            if isinstance(meta.get("agent_audit"), dict)
            else None,
            "source_paths": meta.get("source_paths"),
            "image_paths": [
                im.get("image_path")
                for im in (data.get("images") or [])
                if isinstance(im, dict)
            ],
            "spot_reason": None,
        }
        if meta.get("human_spot_queue") is True or (
            qs == "format_pass"
            and isinstance(meta.get("agent_audit"), dict)
            and meta["agent_audit"].get("verdict") == "needs_human"
        ):
            row["spot_reason"] = "needs_human"
            needs.append(row)
        elif qs == "agent_pass":
            agent_pass.append(row)

    rng = random.Random(args.seed)
    n_sample = int(round(len(agent_pass) * args.sample_rate))
    if agent_pass and args.sample_rate > 0 and n_sample == 0:
        n_sample = 1
    sampled = rng.sample(agent_pass, k=min(n_sample, len(agent_pass))) if agent_pass else []
    for row in sampled:
        row["spot_reason"] = "agent_pass_sample"

    # dedupe by sample_id (needs_human wins)
    by_id: dict[str, dict] = {}
    for row in needs + sampled:
        sid = row.get("sample_id") or ""
        if sid not in by_id or row["spot_reason"] == "needs_human":
            by_id[sid] = row
    final = sorted(by_id.values(), key=lambda r: r.get("sample_id") or "")

    print(
        f"human_spotcheck={len(final)} "
        f"(needs_human={len(needs)} agent_pass_pool={len(agent_pass)} "
        f"sampled={len(sampled)} rate={args.sample_rate} seed={args.seed})"
    )
    for r in final:
        print(
            f"{r['sample_id']}\t{r['spot_reason']}\t{r['task_type']}\t"
            f"qa={r['qa_status']}\tsrc={r.get('source_paths')}\t{r['path']}"
        )

    out = args.jsonl_out or (PENDING / "human_spotcheck.jsonl")
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        for r in final:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
