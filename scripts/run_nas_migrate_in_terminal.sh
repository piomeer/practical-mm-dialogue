#!/usr/bin/env bash
# Run this in Terminal.app (not only Cursor) if SMB writes are blocked for the IDE.
# Usage:
#   ./scripts/run_nas_migrate_in_terminal.sh --dry-run
#   ./scripts/run_nas_migrate_in_terminal.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
if [[ -f .env ]]; then
  # shellcheck disable=SC1091
  set -a
  # only export NAS_ROOT line safely
  NAS_LINE="$(grep -E '^NAS_ROOT=' .env | tail -1 || true)"
  if [[ -n "${NAS_LINE}" ]]; then
    eval "${NAS_LINE}"
    export NAS_ROOT
  fi
  set +a
fi
NAS_ROOT="${NAS_ROOT:-/Volumes/家庭共享/实用多轮对话类图文数据集}"
echo "NAS_ROOT=$NAS_ROOT"
if [[ ! -d "$NAS_ROOT" ]]; then
  echo "Mount SMB first: open 'smb://192.168.31.13/家庭共享'"
  exit 2
fi
mkdir -p "$NAS_ROOT/cold/data" "$NAS_ROOT/cold/data_used" "$NAS_ROOT/cold/data_lt720" "$NAS_ROOT/ledger"
for pool in data data_used data_lt720; do
  for cat in 生活场景 工作场景 收据 文档截图 图表推理 学习材料 代码报错; do
    mkdir -p "$NAS_ROOT/cold/$pool/$cat"
  done
done
export PYTHONUNBUFFERED=1
exec .venv/bin/python scripts/nas_migrate_stable.py "$@"
