#!/usr/bin/env python3
"""Fetch work/office photos from Wikimedia Commons into data/工作场景/.

Unsplash remains a low-volume supplement; Commons is the bulk path for scenes.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import requests

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT_DIR = DATA / "工作场景"
META_PATH = DATA / "_meta" / "index.jsonl"
CATEGORY = "工作场景"
SOURCE = "wikimedia"
API = "https://commons.wikimedia.org/w/api.php"

DEFAULT_QUERIES = [
    "office desk",
    "office meeting",
    "coworking space",
    "conference room",
    "office computer",
    "business office interior",
    "whiteboard meeting",
    "open plan office",
    "office cubicle",
    "workplace laptop",
    "modern office interior",
    "office chair desk",
    "call center office",
    "startup office",
    "corporate lobby office",
    "home office desk",
    "shared desk office",
    "meeting table office",
]


def slugify(text: str, max_len: int = 40) -> str:
    text = str(text).lower().strip()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = text.strip("_") or "office"
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


def search_files(session: requests.Session, query: str, limit: int = 50) -> list[dict]:
    """Return imageinfo dicts for Commons file search hits (with continue)."""
    out = []
    cont = {}
    while len(out) < limit:
        params = {
            "action": "query",
            "format": "json",
            "generator": "search",
            "gsrsearch": f"filetype:bitmap {query}",
            "gsrnamespace": 6,
            "gsrlimit": min(50, limit - len(out)),
            "prop": "imageinfo",
            "iiprop": "url|size|mime|extmetadata",
            "iiurlwidth": 1280,
        }
        params.update(cont)
        r = session.get(API, params=params, timeout=60)
        r.raise_for_status()
        data = r.json()
        pages = (data.get("query") or {}).get("pages") or {}
        if not pages:
            break
        for page in pages.values():
            infos = page.get("imageinfo") or []
            if not infos:
                continue
            info = infos[0]
            info["_pageid"] = page.get("pageid")
            info["_title"] = page.get("title")
            out.append(info)
            if len(out) >= limit:
                break
        cont = data.get("continue") or {}
        if not cont:
            break
        time.sleep(0.3)
    return out


def license_ok(info: dict) -> tuple[bool, str]:
    meta = (info.get("extmetadata") or {})
    lic = (meta.get("LicenseShortName") or {}).get("value") or ""
    lic_url = (meta.get("LicenseUrl") or {}).get("value") or ""
    # allow common open licenses; skip unknown/all-rights
    allowed_tokens = (
        "cc0",
        "public domain",
        "pd",
        "cc-by",
        "cc by",
        "creative commons attribution",
    )
    low = lic.lower()
    if any(t in low for t in allowed_tokens):
        # exclude ND/NC if present in short name when strict; keep BY/SA/CC0/PD
        if "nc" in low.replace(" ", "") and "cc0" not in low:
            return False, lic
        return True, f"{lic} {lic_url}".strip()
    return False, lic or "unknown"


def download_file(session: requests.Session, url: str, dest: Path) -> None:
    with session.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 64):
                if chunk:
                    f.write(chunk)


def main() -> None:
    parser = argparse.ArgumentParser(description="Wikimedia Commons → data/工作场景/")
    parser.add_argument("--limit", type=int, default=100, help="本次最多新保存张数")
    parser.add_argument(
        "--queries",
        type=str,
        default=",".join(DEFAULT_QUERIES),
        help="逗号分隔搜索词",
    )
    parser.add_argument("--sleep", type=float, default=0.4, help="请求间隔秒")
    parser.add_argument("--per-query", type=int, default=80, help="每个关键词最多检索条数")
    args = parser.parse_args()

    queries = [q.strip() for q in args.queries.split(",") if q.strip()]
    rows = read_meta_rows()
    seen = existing_source_ids(rows)
    next_idx = next_index_for_category(rows, CATEGORY)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "practical-mm-dialogue-dataset/0.1 (research; local dataset build)",
            "Accept": "application/json",
        }
    )

    print(f"目标目录: {OUT_DIR}")
    print(f"已有 wikimedia id: {len(seen)}；本次 limit={args.limit}")

    saved = 0
    for query in queries:
        if saved >= args.limit:
            break
        try:
            hits = search_files(session, query, limit=args.per_query)
        except Exception as e:
            print(f"[search fail] {query}: {e}", file=sys.stderr)
            time.sleep(args.sleep * 2)
            continue
        time.sleep(args.sleep)

        for info in hits:
            if saved >= args.limit:
                break
            mime = (info.get("mime") or "").lower()
            if not mime.startswith("image/"):
                continue
            if mime not in {"image/jpeg", "image/png", "image/webp"}:
                continue
            width = info.get("width") or 0
            height = info.get("height") or 0
            if width < 400 or height < 300:
                continue

            ok, lic = license_ok(info)
            if not ok:
                continue

            url = info.get("thumburl") or info.get("url")
            title = info.get("_title") or url
            sid = str(info.get("_pageid") or title)
            if not url or sid in seen:
                continue

            slug = slugify(Path(str(title).replace("File:", "")).stem)
            filename = f"{next_idx:04d}{slug}.jpg"
            # keep original ext if png preferred; normalize to jpg name but save bytes as-is
            ext = ".jpg"
            if "png" in mime:
                ext = ".png"
            elif "webp" in mime:
                ext = ".webp"
            filename = f"{next_idx:04d}{slug}{ext}"
            dest = OUT_DIR / filename
            while dest.exists():
                next_idx += 1
                filename = f"{next_idx:04d}{slug}{ext}"
                dest = OUT_DIR / filename

            try:
                download_file(session, url, dest)
            except Exception as e:
                print(f"[download fail] {sid}: {e}", file=sys.stderr)
                if dest.exists():
                    dest.unlink()
                time.sleep(args.sleep)
                continue

            row = {
                "local_path": f"{CATEGORY}/{filename}",
                "category": CATEGORY,
                "source": SOURCE,
                "source_id": sid,
                "license": lic,
                "query": query,
                "width": width,
                "height": height,
                "downloaded_at": datetime.now(timezone.utc).isoformat(),
                "needs_redact": False,
                "commons_title": title,
                "commons_url": info.get("descriptionurl")
                or f"https://commons.wikimedia.org/wiki/{quote(str(title).replace(' ', '_'))}",
            }
            append_meta(row)
            seen.add(sid)
            next_idx += 1
            saved += 1
            print(f"saved {saved}/{args.limit}: {filename} (query={query})")
            time.sleep(args.sleep)

    print(f"完成：新保存 {saved} 张 → {OUT_DIR}")
    if saved == 0:
        sys.exit(2)


if __name__ == "__main__":
    main()
