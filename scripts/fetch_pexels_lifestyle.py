#!/usr/bin/env python3
"""Fetch lifestyle photos from Pexels API into data/生活场景/ with _meta records."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv
from PIL import Image

# Allow very large Pexels originals (some exceed Pillow default pixel cap).
Image.MAX_IMAGE_PIXELS = None

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT_DIR = DATA / "生活场景"
META_PATH = DATA / "_meta" / "index.jsonl"
CATEGORY = "生活场景"
SOURCE = "pexels"
API = "https://api.pexels.com/v1"

DEFAULT_QUERIES = [
    "picnic",
    "beach",
    "cafe",
    "travel",
    "home interior",
    "park",
    "food table",
    "weekend lifestyle",
    "family dinner",
    "cooking kitchen",
    "coffee shop",
    "street market",
    "hiking trail",
    "camping tent",
    "yoga outdoor",
    "city walk",
    "sunset beach",
    "bookstore cafe",
    "living room",
    "bedroom cozy",
    "garden flowers",
    "farmers market",
    "brunch table",
    "friends laughing",
    "bicycle city",
    "museum visit",
    "lake picnic",
    "mountain view",
    "rainy window",
    "night city lights",
    "breakfast flatlay",
    "pet dog home",
    "cat sofa",
    "shopping street",
    "bakery pastry",
    "wine dinner",
    "apartment balcony",
    "cozy reading",
]


def load_key() -> str:
    load_dotenv(ROOT / ".env")
    key = os.getenv("PEXELS_API_KEY", "").strip()
    if not key:
        print(
            "缺少 PEXELS_API_KEY。\n"
            "1) 打开 https://www.pexels.com/api/ 申请 API Key\n"
            "2) 写入仓库根目录 .env（可参考 .env.example）",
            file=sys.stderr,
        )
        sys.exit(1)
    return key


def slugify(text: str, max_len: int = 40) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = text.strip("_") or "photo"
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


def pick_src(photo: dict) -> str | None:
    src = photo.get("src") or {}
    return src.get("original") or src.get("large2x") or src.get("large") or src.get("medium")


def download_file(session: requests.Session, url: str, dest: Path) -> None:
    with session.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 64):
                if chunk:
                    f.write(chunk)


def main() -> None:
    parser = argparse.ArgumentParser(description="Pexels → data/生活场景/")
    parser.add_argument("--limit", type=int, default=20, help="本次最多新下载张数")
    parser.add_argument(
        "--fill-to",
        type=int,
        default=0,
        help="将本目录图片总数补到该值（优先于 --limit；按磁盘现有张数计算缺口）",
    )
    parser.add_argument(
        "--queries",
        type=str,
        default=",".join(DEFAULT_QUERIES),
        help="逗号分隔搜索词",
    )
    parser.add_argument("--sleep", type=float, default=0.5, help="请求间隔秒")
    parser.add_argument("--per-page", type=int, default=40, help="每页条数(<=80)")
    parser.add_argument(
        "--min-short-side",
        type=int,
        default=720,
        help="最短边像素下限（不含更小）",
    )
    args = parser.parse_args()

    key = load_key()
    queries = [q.strip() for q in args.queries.split(",") if q.strip()]
    if not queries:
        print("queries 为空", file=sys.stderr)
        sys.exit(1)

    rows = read_meta_rows()
    seen_ids = existing_source_ids(rows)
    next_idx = next_index_for_category(rows, CATEGORY)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    if args.fill_to > 0:
        have = sum(
            1
            for p in OUT_DIR.iterdir()
            if p.is_file() and p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
        )
        args.limit = max(0, args.fill_to - have)
        print(f"目录已有 {have}，fill-to={args.fill_to} → 本次 limit={args.limit}", flush=True)
        if args.limit == 0:
            print("已达目标，无需下载。", flush=True)
            return

    session = requests.Session()
    session.headers.update(
        {
            "Authorization": key,
            "User-Agent": "practical-mm-dialogue-dataset/0.1",
        }
    )

    saved = 0
    page_by_query = {q: 1 for q in queries}
    exhausted = set()
    q_cycle = 0
    failures = 0
    idle_rounds = 0

    print(f"目标目录: {OUT_DIR}", flush=True)
    print(f"已有 pexels id: {len(seen_ids)}；本次 limit={args.limit}", flush=True)

    while saved < args.limit:
        active = [q for q in queries if q not in exhausted]
        if not active:
            print("所有 query 已翻尽或无新图，停止。", file=sys.stderr, flush=True)
            break
        query = active[q_cycle % len(active)]
        q_cycle += 1
        page = page_by_query[query]
        before = saved
        try:
            r = session.get(
                f"{API}/search",
                params={
                    "query": query,
                    "page": page,
                    "per_page": min(args.per_page, 80),
                    "orientation": "landscape",
                    "size": "large",
                },
                timeout=60,
            )
            r.raise_for_status()
            payload = r.json()
            results = payload.get("photos") or []
            total = payload.get("total_results")
        except requests.HTTPError as e:
            code = e.response.status_code if e.response is not None else None
            failures += 1
            print(f"[search fail] query={query} page={page}: {e}", file=sys.stderr)
            if code in (401, 403, 429):
                print("触发 Pexels 鉴权/速率限制，停止本批。", file=sys.stderr)
                break
            if failures >= 8:
                print("连续失败过多，停止。", file=sys.stderr)
                break
            time.sleep(args.sleep * 2)
            continue

        if not results:
            exhausted.add(query)
            print(f"[exhaust] query={query!r} page={page} 无结果", flush=True)
            time.sleep(args.sleep)
            continue

        # Pexels typically caps deep pagination; stop a query when page is past available.
        if isinstance(total, int) and total >= 0:
            max_page = max(1, (total + min(args.per_page, 80) - 1) // min(args.per_page, 80))
            if page >= max_page:
                exhausted.add(query)

        page_by_query[query] = page + 1

        for photo in results:
            if saved >= args.limit:
                break
            pid = photo.get("id")
            if pid is None:
                continue
            sid = str(pid)
            if sid in seen_ids:
                continue

            api_w = photo.get("width")
            api_h = photo.get("height")
            if (
                isinstance(api_w, int)
                and isinstance(api_h, int)
                and min(api_w, api_h) < args.min_short_side
            ):
                seen_ids.add(sid)
                continue

            alt = photo.get("alt") or query
            slug = slugify(alt if isinstance(alt, str) else query)
            filename = f"{next_idx:04d}{slug}.jpg"
            dest = OUT_DIR / filename
            while dest.exists():
                next_idx += 1
                filename = f"{next_idx:04d}{slug}.jpg"
                dest = OUT_DIR / filename

            file_url = pick_src(photo)
            if not file_url:
                continue

            try:
                download_file(session, file_url, dest)
            except Exception as e:
                failures += 1
                print(f"[download fail] id={sid}: {e}", file=sys.stderr)
                if dest.exists():
                    dest.unlink()
                time.sleep(args.sleep)
                continue

            try:
                with Image.open(dest) as im:
                    w, h = im.size
                    im = im.convert("RGB")
                    im.save(dest, format="JPEG", quality=92)
            except Exception as e:
                print(f"[open fail] {filename}: {e}", file=sys.stderr)
                dest.unlink(missing_ok=True)
                continue

            if min(w, h) < args.min_short_side:
                print(
                    f"[skip small] {filename}: {w}x{h} short_side<{args.min_short_side}",
                    file=sys.stderr,
                )
                dest.unlink(missing_ok=True)
                seen_ids.add(sid)
                continue

            photographer = (photo.get("photographer") or "")[:120]
            page_url = photo.get("url") or ""
            row = {
                "local_path": f"{CATEGORY}/{filename}",
                "category": CATEGORY,
                "source": SOURCE,
                "source_id": sid,
                "license": "Pexels License (https://www.pexels.com/license/)",
                "query": query,
                "width": w,
                "height": h,
                "downloaded_at": datetime.now(timezone.utc).isoformat(),
                "needs_redact": False,
                "photographer": photographer,
                "pexels_page": page_url,
            }
            append_meta(row)
            seen_ids.add(sid)
            next_idx += 1
            saved += 1
            failures = 0
            print(
                f"saved {saved}/{args.limit}: {filename} ({w}x{h}, query={query}, id={sid})",
                flush=True,
            )
            time.sleep(args.sleep)

        if saved == before:
            idle_rounds += 1
            if idle_rounds >= len(active) * 3:
                # Entire page(s) were duplicates; advance may still help, but avoid endless spin.
                if page > 80:
                    exhausted.add(query)
                    print(f"[exhaust] query={query!r} 连续无新图且 page>{page}", flush=True)
        else:
            idle_rounds = 0

    print(f"完成：新下载 {saved} 张 → {OUT_DIR}", flush=True)
    if saved == 0:
        sys.exit(2)


if __name__ == "__main__":
    main()
