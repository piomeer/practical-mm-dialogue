#!/usr/bin/env python3
"""Fetch lifestyle photos from Unsplash API into data/生活场景/ with _meta records."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT_DIR = DATA / "生活场景"
META_PATH = DATA / "_meta" / "index.jsonl"
CATEGORY = "生活场景"
SOURCE = "unsplash"
API = "https://api.unsplash.com"

DEFAULT_QUERIES = [
    "picnic",
    "beach",
    "cafe",
    "travel",
    "home interior",
    "park",
    "food table",
    "weekend lifestyle",
]


def load_key() -> str:
    load_dotenv(ROOT / ".env")
    key = os.getenv("UNSPLASH_ACCESS_KEY", "").strip()
    if not key:
        print(
            "缺少 UNSPLASH_ACCESS_KEY。\n"
            "1) 打开 https://unsplash.com/oauth/applications 创建应用\n"
            "2) 复制 Access Key 写入仓库根目录 .env（可参考 .env.example）",
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
        r["source_id"]
        for r in rows
        if r.get("source") == SOURCE and r.get("source_id")
    }


def next_index_for_category(rows: list[dict], category: str) -> int:
    pattern = re.compile(r"^(\d{4,5})(?=[A-Za-z])")
    max_n = 0
    # also scan files on disk
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


def search_photos(session: requests.Session, query: str, page: int, per_page: int) -> list[dict]:
    r = session.get(
        f"{API}/search/photos",
        params={"query": query, "page": page, "per_page": per_page, "orientation": "landscape"},
        timeout=60,
    )
    r.raise_for_status()
    return r.json().get("results", [])


def trigger_download(session: requests.Session, download_location: str) -> str:
    """Unsplash guideline: hit download_location before hotlinking the file."""
    r = session.get(download_location, timeout=60)
    r.raise_for_status()
    data = r.json()
    return data.get("url") or download_location


def download_file(session: requests.Session, url: str, dest: Path) -> None:
    with session.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 64):
                if chunk:
                    f.write(chunk)


def pick_file_url(photo: dict, *, min_short_side: int) -> str | None:
    """Prefer a URL likely to keep short side >= min_short_side (regular is often ~1080w)."""
    urls = photo.get("urls") or {}
    full = urls.get("full")
    raw = urls.get("raw")
    regular = urls.get("regular")
    # Ask Unsplash CDN for a long edge that keeps short side above threshold for common ratios.
    target_long = max(1600, int(min_short_side * 16 / 9) + 80)
    for base in (full, raw, regular):
        if not base:
            continue
        if "images.unsplash.com" in base:
            sep = "&" if "?" in base else "?"
            return f"{base}{sep}w={target_long}&fit=max&q=80"
        return base
    return urls.get("small")


def main() -> None:
    parser = argparse.ArgumentParser(description="Unsplash → data/生活场景/")
    parser.add_argument("--limit", type=int, default=20, help="本次最多新下载张数")
    parser.add_argument(
        "--queries",
        type=str,
        default=",".join(DEFAULT_QUERIES),
        help="逗号分隔搜索词",
    )
    parser.add_argument("--sleep", type=float, default=0.8, help="请求间隔秒")
    parser.add_argument("--per-page", type=int, default=10, help="每页条数(<=30)")
    parser.add_argument(
        "--min-short-side",
        type=int,
        default=720,
        help="最短边像素下限（不含更小；与 data_lt720 规则一致）",
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

    session = requests.Session()
    session.headers.update(
        {
            "Accept-Version": "v1",
            "Authorization": f"Client-ID {key}",
            "User-Agent": "practical-mm-dialogue-dataset/0.1",
        }
    )

    saved = 0
    page_by_query = {q: 1 for q in queries}
    q_cycle = 0
    failures = 0

    print(f"目标目录: {OUT_DIR}")
    print(f"已有 unsplash id: {len(seen_ids)}；本次 limit={args.limit}")

    while saved < args.limit:
        query = queries[q_cycle % len(queries)]
        q_cycle += 1
        page = page_by_query[query]
        try:
            results = search_photos(session, query, page, min(args.per_page, 30))
        except requests.HTTPError as e:
            code = e.response.status_code if e.response is not None else None
            failures += 1
            print(f"[search fail] query={query} page={page}: {e}", file=sys.stderr)
            if code in (403, 429):
                print("触发 Unsplash 速率限制，停止本批。", file=sys.stderr)
                break
            if failures >= 8:
                print("连续失败过多，停止。", file=sys.stderr)
                break
            time.sleep(args.sleep * 2)
            continue

        if not results:
            page_by_query[query] = page + 1
            if page > 20:
                # give up this query deepening
                time.sleep(args.sleep)
            continue

        page_by_query[query] = page + 1

        for photo in results:
            if saved >= args.limit:
                break
            pid = photo.get("id")
            if not pid or pid in seen_ids:
                continue

            api_w = photo.get("width")
            api_h = photo.get("height")
            if (
                isinstance(api_w, int)
                and isinstance(api_h, int)
                and min(api_w, api_h) < args.min_short_side
            ):
                seen_ids.add(pid)  # skip permanently this run / meta-less
                continue

            alt = photo.get("alt_description") or photo.get("description") or query
            slug = slugify(alt if isinstance(alt, str) else query)
            filename = f"{next_idx:04d}{slug}.jpg"
            dest = OUT_DIR / filename
            while dest.exists():
                next_idx += 1
                filename = f"{next_idx:04d}{slug}.jpg"
                dest = OUT_DIR / filename

            file_url = pick_file_url(photo, min_short_side=args.min_short_side)
            download_loc = (photo.get("links") or {}).get("download_location")
            if not file_url:
                continue

            try:
                if download_loc:
                    # Guideline ping; still download a sized URL we control.
                    trigger_download(session, download_loc)
                    time.sleep(args.sleep)
                download_file(session, file_url, dest)
            except Exception as e:
                failures += 1
                print(f"[download fail] id={pid}: {e}", file=sys.stderr)
                if dest.exists():
                    dest.unlink()
                time.sleep(args.sleep)
                continue

            try:
                from PIL import Image

                with Image.open(dest) as im:
                    w, h = im.size
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
                seen_ids.add(pid)
                continue

            license_note = "Unsplash License (https://unsplash.com/license)"
            row = {
                "local_path": f"{CATEGORY}/{filename}",
                "category": CATEGORY,
                "source": SOURCE,
                "source_id": pid,
                "license": license_note,
                "query": query,
                "width": w,
                "height": h,
                "downloaded_at": datetime.now(timezone.utc).isoformat(),
                "needs_redact": False,
                "photographer": ((photo.get("user") or {}).get("name")),
                "unsplash_page": ((photo.get("links") or {}).get("html")),
            }
            append_meta(row)
            seen_ids.add(pid)
            next_idx += 1
            saved += 1
            failures = 0
            print(f"saved {saved}/{args.limit}: {filename} ({w}x{h}, query={query}, id={pid})")
            time.sleep(args.sleep)

    print(f"完成：新下载 {saved} 张 → {OUT_DIR}")
    if saved == 0:
        sys.exit(2)


if __name__ == "__main__":
    main()
