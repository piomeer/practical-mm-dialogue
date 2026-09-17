#!/usr/bin/env python3
"""Fetch PlotQA plot images from Hugging Face into data/图表推理/ with _meta records."""

from __future__ import annotations

import argparse
import hashlib
import io
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
OUT_DIR = DATA / "图表推理"
META_PATH = DATA / "_meta" / "index.jsonl"
CATEGORY = "图表推理"
SOURCE = "plotqa"
HF_ID = "achang/plot_qa"
LICENSE = (
    "CC-BY-4.0; PlotQA (Methani et al., WACV 2020); "
    "https://iitmnlp.github.io/PlotQA/ ; "
    "https://huggingface.co/datasets/achang/plot_qa"
)


def slugify(text: str, max_len: int = 40) -> str:
    text = str(text).lower().strip()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = text.strip("_") or "plot"
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
    pattern = re.compile(r"^(\d{4})")
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


def open_image(raw) -> Image.Image:
    if isinstance(raw, Image.Image):
        return raw.convert("RGB")
    if isinstance(raw, (bytes, bytearray)):
        return Image.open(io.BytesIO(raw)).convert("RGB")
    if isinstance(raw, dict) and "bytes" in raw:
        return Image.open(io.BytesIO(raw["bytes"])).convert("RGB")
    if hasattr(raw, "convert"):
        return raw.convert("RGB")
    raise TypeError(f"unsupported image type: {type(raw)}")


def image_source_id(image: Image.Image) -> str:
    # Faster than re-encoding PNG; enough to dedupe shared plots across QA rows.
    digest = hashlib.sha1(image.tobytes()).hexdigest()[:16]
    return f"plotqa_{digest}"


def main() -> None:
    parser = argparse.ArgumentParser(description="PlotQA → data/图表推理/")
    parser.add_argument("--limit", type=int, default=100, help="本次最多新保存张数（按唯一图）")
    parser.add_argument(
        "--split",
        type=str,
        default="train",
        choices=["train", "validation", "test"],
        help="数据集划分",
    )
    parser.add_argument(
        "--min-short-side",
        type=int,
        default=600,
        help="最短边像素下限（PlotQA 原图短边多在 600–719，默认 600；需要更严可传 720）",
    )
    args = parser.parse_args()

    rows = read_meta_rows()
    seen = existing_source_ids(rows)
    next_idx = next_index_for_category(rows, CATEGORY)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"流式加载 {HF_ID} split={args.split} …", flush=True)
    ds = load_dataset(HF_ID, split=args.split, streaming=True)
    print(f"已有 plotqa id: {len(seen)}；本次 limit={args.limit}", flush=True)

    saved = 0
    scanned = 0
    skipped_small = 0
    for example in ds:
        if saved >= args.limit:
            break
        scanned += 1
        try:
            image = open_image(example.get("image"))
        except Exception as e:
            print(f"跳过无法读取 row={scanned}: {e}", file=sys.stderr)
            continue

        w, h = image.size
        if min(w, h) < args.min_short_side:
            skipped_small += 1
            continue

        sid = image_source_id(image)
        if sid in seen:
            continue

        text = example.get("text") or ""
        slug = slugify(f"plotqa_{text[:24]}" if text else "plotqa")
        filename = f"{next_idx:04d}{slug}.jpg"
        dest = OUT_DIR / filename
        while dest.exists():
            next_idx += 1
            filename = f"{next_idx:04d}{slug}.jpg"
            dest = OUT_DIR / filename

        image.save(dest, format="JPEG", quality=92)
        row = {
            "local_path": f"{CATEGORY}/{filename}",
            "category": CATEGORY,
            "source": SOURCE,
            "source_id": sid,
            "license": LICENSE,
            "query": str(text)[:200],
            "width": w,
            "height": h,
            "downloaded_at": datetime.now(timezone.utc).isoformat(),
            "needs_redact": False,
            "hf_dataset": HF_ID,
            "hf_split": args.split,
        }
        append_meta(row)
        seen.add(sid)
        next_idx += 1
        saved += 1
        print(f"saved {saved}/{args.limit}: {filename} ({w}x{h}, id={sid})")

    print(
        f"完成：新保存 {saved} 张（扫描 {scanned} 条，短边不足跳过 {skipped_small}）→ {OUT_DIR}"
    )
    if saved == 0:
        sys.exit(2)
    os._exit(0)


if __name__ == "__main__":
    main()
