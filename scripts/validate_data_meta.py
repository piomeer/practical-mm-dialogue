#!/usr/bin/env python3
"""Validate data/_meta/index.jsonl against files in data/ or data_used/."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DATA_USED = ROOT / "data_used"
META = DATA / "_meta" / "index.jsonl"
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}


def pool_root(row: dict) -> Path:
    return DATA_USED if row.get("used") else DATA


def count_images(folder: Path) -> int:
    if not folder.is_dir():
        return 0
    return sum(1 for p in folder.iterdir() if p.suffix.lower() in IMAGE_EXTS)


def main() -> int:
    if not META.exists():
        print(f"missing {META}", file=sys.stderr)
        return 1
    rows = []
    for i, line in enumerate(META.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as e:
            print(f"line {i}: invalid json: {e}", file=sys.stderr)
            return 1

    missing = []
    used_n = 0
    unused_n = 0
    for r in rows:
        is_used = bool(r.get("used"))
        if is_used:
            used_n += 1
        else:
            unused_n += 1
        p = pool_root(r) / r["local_path"]
        if not p.is_file():
            missing.append(f"{'data_used' if is_used else 'data'}/{r['local_path']}")

    print(f"meta rows: {len(rows)} (unused={unused_n}, used={used_n})")
    print(f"missing files: {len(missing)}")
    for m in missing:
        print(f"  - {m}")

    print("dir (unused pool data/):")
    for d in sorted(DATA.iterdir()):
        if not d.is_dir() or d.name.startswith("_"):
            continue
        print(f"  {d.name}: {count_images(d)} images")

    if DATA_USED.is_dir():
        print("dir (used pool data_used/):")
        for d in sorted(DATA_USED.iterdir()):
            if not d.is_dir() or d.name.startswith("_"):
                continue
            print(f"  {d.name}: {count_images(d)} images")

    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
