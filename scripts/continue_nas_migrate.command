#!/bin/bash
cd "/Users/mobiwusi-zz-001/Desktop/实用多轮对话类图文数据集" || exit 1
export NAS_ROOT="/Volumes/家庭共享/实用多轮对话类图文数据集"
echo "=== NAS migrate continue (data pool) ==="
echo "NAS_ROOT=$NAS_ROOT"
date
if [[ ! -d "$NAS_ROOT/cold" ]]; then
  echo "ERROR: NAS cold missing. Mount smb://192.168.31.13/家庭共享 first."
  read -r -p "Press Enter to close..."
  exit 2
fi
mkdir -p "$NAS_ROOT/cold/data" "$NAS_ROOT/cold/data_used" "$NAS_ROOT/cold/data_lt720" "$NAS_ROOT/ledger"
for cat in 生活场景 工作场景 收据 文档截图 图表推理 学习材料 代码报错; do
  mkdir -p "$NAS_ROOT/cold/data/$cat" "$NAS_ROOT/cold/data_used/$cat" "$NAS_ROOT/cold/data_lt720/$cat"
done
./.venv/bin/python scripts/nas_migrate_stable.py --pool data --min-age-minutes 45 2>&1 | tee /tmp/nas_migrate_continue.log
echo "EXIT:$?"
du -sh data || true
./.venv/bin/python scripts/rebuild_image_inventory.py --also-nas-ledger || true
echo "Done. Log: /tmp/nas_migrate_continue.log"
read -r -p "Press Enter to close..."
