#!/usr/bin/env python3
"""Validate data/_meta/index.jsonl against files in data/, data_used/, or data_lt720/."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DATA_USED = ROOT / "data_used"
DATA_LT720 = ROOT / "data_lt720"
META = DATA / "_meta" / "index.jsonl"
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}


def pool_root(row: dict) -> Path:
    if row.get("short_side_lt720"):
        return DATA_LT720
    return DATA_USED if row.get("used") else DATA


def pool_label(row: dict) -> str:
    if row.get("short_side_lt720"):
        return "data_lt720"
    return "data_used" if row.get("used") else "data"


def count_images(folder: Path) -> int:
    if not folder.is_dir():
        return 0
    return sum(1 for p in folder.iterdir() if p.suffix.lower() in IMAGE_EXTS)


def print_pool(label: str, root: Path) -> None:
    if not root.is_dir():
        return
    print(f"dir ({label}):")
    for d in sorted(root.iterdir()):
        if not d.is_dir() or d.name.startswith("_"):
            continue
        print(f"  {d.name}: {count_images(d)} images")


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
    lt720_n = 0
    for r in rows:
        if r.get("short_side_lt720"):
            lt720_n += 1
        elif r.get("used"):
            used_n += 1
        else:
            unused_n += 1
        p = pool_root(r) / r["local_path"]
        if not p.is_file():
            missing.append(f"{pool_label(r)}/{r['local_path']}")

    print(
        f"meta rows: {len(rows)} "
        f"(unused={unused_n}, used={used_n}, short_side_lt720={lt720_n})"
    )
    print(f"missing files: {len(missing)}")
    for m in missing:
        print(f"  - {m}")

    print_pool("unused pool data/", DATA)
    print_pool("used pool data_used/", DATA_USED)
    print_pool("short-side <720 pool data_lt720/", DATA_LT720)

    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
