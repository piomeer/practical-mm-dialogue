#!/usr/bin/env python3
"""Migrate stable local pool images to NAS cold store (free disk; skip recent mtime)."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
POOLS = ("data", "data_used", "data_lt720")
SKIP_DIR_NAMES = {"_meta", ".git"}


def load_nas_root() -> Path:
    env_path = ROOT / ".env"
    if env_path.is_file():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("NAS_ROOT=") and not line.startswith("#"):
                val = line.split("=", 1)[1].strip().strip('"').strip("'")
                if val:
                    return Path(val)
    env = os.environ.get("NAS_ROOT", "").strip()
    if env:
        return Path(env)
    return Path("/Volumes/家庭共享/实用多轮对话类图文数据集")


def iter_images(pool_dir: Path) -> list[Path]:
    out: list[Path] = []
    if not pool_dir.is_dir():
        return out
    for p in pool_dir.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower() not in IMAGE_EXTS:
            continue
        # skip under _meta
        if any(part in SKIP_DIR_NAMES for part in p.parts):
            continue
        out.append(p)
    return out


def rel_under_pool(pool_dir: Path, file_path: Path) -> str:
    return str(file_path.relative_to(pool_dir)).replace("\\", "/")


def migrate_one(
    src: Path,
    dst: Path,
    *,
    dry_run: bool,
) -> str:
    if dry_run:
        return "would_move"
    dst.parent.mkdir(parents=True, exist_ok=True)
    # data-only copy: shutil.copy2 → fchmod hangs on some SMB (Huawei) mounts
    # prefer plain read/write to avoid macOS fcopyfile stalls on smbfs
    with open(src, "rb") as fsrc, open(dst, "wb") as fdst:
        shutil.copyfileobj(fsrc, fdst, length=8 * 1024 * 1024)
    if not dst.is_file():
        return "copy_missing"
    if dst.stat().st_size != src.stat().st_size or dst.stat().st_size == 0:
        try:
            dst.unlink(missing_ok=True)
        except OSError:
            pass
        return "size_mismatch"
    src.unlink()
    return "moved"


def handle_one(
    src: Path,
    dst: Path,
    size: int,
    *,
    dry_run: bool,
) -> tuple[str, int, str]:
    """Return (status, bytes_freed_if_any, rel_hint)."""
    rel = str(dst)
    try:
        if dst.is_file() and dst.stat().st_size == size:
            if dry_run:
                return "would_dedupe_local", size, rel
            try:
                src.unlink()
                return "dedupe_local", size, rel
            except OSError:
                return "dedupe_fail", 0, rel
        status = migrate_one(src, dst, dry_run=dry_run)
        freed = size if status in {"moved", "would_move"} else 0
        return status, freed, rel
    except OSError as e:
        return f"error:{type(e).__name__}", 0, f"{src} -> {dst}: {e}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Move stable images from local pools to NAS cold/ (skip recent mtime)"
    )
    parser.add_argument(
        "--pool",
        action="append",
        choices=list(POOLS),
        default=None,
        help="limit to pool(s); default: data_used, data_lt720, data",
    )
    parser.add_argument(
        "--min-age-minutes",
        type=float,
        default=45.0,
        help="skip files newer than this many minutes (default 45)",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=0, help="max files to process (0=all)")
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="parallel copy workers (default 4; helps SMB throughput)",
    )
    parser.add_argument(
        "--nas-root",
        type=Path,
        default=None,
        help="override NAS_ROOT",
    )
    args = parser.parse_args()

    nas_root = args.nas_root or load_nas_root()
    cold = nas_root / "cold"
    if not nas_root.is_dir():
        print(f"NAS_ROOT not mounted or missing: {nas_root}", file=sys.stderr)
        print("Connect smb://192.168.31.13/家庭共享 then retry.", file=sys.stderr)
        return 2

    # ensure writable
    try:
        cold.mkdir(parents=True, exist_ok=True)
        probe = cold / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
    except OSError as e:
        print(f"NAS not writable: {cold} ({e})", file=sys.stderr)
        return 2

    pools = args.pool or ["data_used", "data_lt720", "data"]
    min_age = args.min_age_minutes * 60.0
    now = time.time()
    counts: dict[str, int] = {}
    bytes_free = 0
    processed = 0
    workers = max(1, args.workers)

    print(
        f"NAS_ROOT={nas_root} pools={pools} min_age_min={args.min_age_minutes} "
        f"dry_run={args.dry_run} workers={workers}",
        flush=True,
    )

    jobs: list[tuple[Path, Path, int]] = []
    for pool in pools:
        pool_dir = ROOT / pool
        images = iter_images(pool_dir)
        for src in images:
            if args.limit and len(jobs) >= args.limit:
                break
            try:
                st = src.stat()
            except OSError:
                counts["stat_fail"] = counts.get("stat_fail", 0) + 1
                continue
            if st.st_size <= 0:
                counts["empty"] = counts.get("empty", 0) + 1
                continue
            age = now - st.st_mtime
            if age < min_age:
                counts["skip_recent"] = counts.get("skip_recent", 0) + 1
                continue
            rel = rel_under_pool(pool_dir, src)
            dst = cold / pool / rel
            jobs.append((src, dst, st.st_size))
        if args.limit and len(jobs) >= args.limit:
            break

    print(f"queued={len(jobs)}", flush=True)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {
            ex.submit(handle_one, src, dst, size, dry_run=args.dry_run): (src, dst)
            for src, dst, size in jobs
        }
        for fut in as_completed(futures):
            status, freed, hint = fut.result()
            counts[status] = counts.get(status, 0) + 1
            if status.startswith("error:"):
                print(status, hint, file=sys.stderr, flush=True)
            bytes_free += freed
            if status in {
                "moved",
                "would_move",
                "dedupe_local",
                "would_dedupe_local",
            }:
                processed += 1
                if processed % 50 == 0:
                    print(f"... processed={processed} last={hint}", flush=True)

    mb = bytes_free / (1024 * 1024)
    print("summary:", ", ".join(f"{k}={v}" for k, v in sorted(counts.items())), flush=True)
    print(
        f"approx_bytes={'would_free' if args.dry_run else 'freed'}={bytes_free} ({mb:.1f} MiB)",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
