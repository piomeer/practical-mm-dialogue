#!/usr/bin/env python3
"""Fetch SROIE receipt images from Hugging Face into data/收据/ with _meta records."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from datasets import load_dataset
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT_DIR = DATA / "收据"
META_PATH = DATA / "_meta" / "index.jsonl"
CATEGORY = "收据"
SOURCE = "sroie"
HF_ID = "jsdnrs/ICDAR2019-SROIE"
LICENSE = (
    "CC-BY-4.0; ICDAR2019 SROIE "
    "(https://rrc.cvc.uab.es/?ch=13; https://huggingface.co/datasets/jsdnrs/ICDAR2019-SROIE)"
)


def slugify(text: str, max_len: int = 40) -> str:
    text = str(text).lower().strip()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = text.strip("_") or "receipt"
    return text[:max_len]


def read_meta_rows() -> list[dict]:
    if not META_PATH.exists():
        return []
    rows = []
    for line in META_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def existing_source_ids(rows: list[dict]) -> set[str]:
    return {
        str(r["source_id"])
        for r in rows
        if r.get("source") == SOURCE and r.get("source_id") is not None
    }


def next_index_for_category(rows: list[dict], category: str) -> int:
    pattern = re.compile(r"^(\d{4,5})(?=[A-Za-z])")
    max_n = 0
    cat_dir = DATA / category
    if cat_dir.exists():
        for p in cat_dir.iterdir():
            if p.is_file() and p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
                m = pattern.match(p.name)
                if m:
                    max_n = max(max_n, int(m.group(1)))
    for r in rows:
        if r.get("category") != category:
            continue
        name = Path(r.get("local_path", "")).name
        m = pattern.match(name)
        if m:
            max_n = max(max_n, int(m.group(1)))
    return max_n + 1


def append_meta(row: dict) -> None:
    META_PATH.parent.mkdir(parents=True, exist_ok=True)
    with META_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def sample_id(example: dict, index: int) -> str:
    for key in ("file_name", "filename", "id", "image_id", "key"):
        val = example.get(key)
        if val is not None and str(val).strip():
            return str(val).strip()
    return f"sroie_{index:05d}"


def main() -> None:
    parser = argparse.ArgumentParser(description="SROIE → data/收据/")
    parser.add_argument("--limit", type=int, default=100, help="本次最多新保存张数")
    parser.add_argument(
        "--split",
        type=str,
        default="train",
        choices=["train", "test", "all"],
        help="数据集划分",
    )
    args = parser.parse_args()

    rows = read_meta_rows()
    seen = existing_source_ids(rows)
    next_idx = next_index_for_category(rows, CATEGORY)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    split = "train+test" if args.split == "all" else args.split
    print(f"加载 {HF_ID} split={split} …")
    ds = load_dataset(HF_ID, split=split)
    print(f"数据集条数: {len(ds)}；已有 sroie id: {len(seen)}；本次 limit={args.limit}")

    saved = 0
    for i, example in enumerate(ds):
        if saved >= args.limit:
            break
        sid = sample_id(example, i)
        if sid in seen:
            continue

        image = example.get("image")
        if image is None:
            continue
        if not isinstance(image, Image.Image):
            # datasets may return dict-like; try convert
            try:
                image = image.convert("RGB")
            except Exception:
                print(f"跳过无法读取的 image: {sid}", file=sys.stderr)
                continue
        else:
            image = image.convert("RGB")

        slug = slugify(f"sroie_{sid}")
        filename = f"{next_idx:04d}{slug}.jpg"
        dest = OUT_DIR / filename
        while dest.exists():
            next_idx += 1
            filename = f"{next_idx:04d}{slug}.jpg"
            dest = OUT_DIR / filename

        dest.parent.mkdir(parents=True, exist_ok=True)
        image.save(dest, format="JPEG", quality=92)

        w, h = image.size
        row = {
            "local_path": f"{CATEGORY}/{filename}",
            "category": CATEGORY,
            "source": SOURCE,
            "source_id": sid,
            "license": LICENSE,
            "query": "",
            "width": w,
            "height": h,
            "downloaded_at": datetime.now(timezone.utc).isoformat(),
            "needs_redact": True,
            "hf_dataset": HF_ID,
            "hf_split": args.split,
        }
        append_meta(row)
        seen.add(sid)
        next_idx += 1
        saved += 1
        print(f"saved {saved}/{args.limit}: {filename} (id={sid})")

    print(f"完成：新保存 {saved} 张 → {OUT_DIR}")
    if saved == 0:
        sys.exit(2)
    # datasets streaming can hang on interpreter shutdown; force-exit after success
    os._exit(0)


if __name__ == "__main__":
    main()
