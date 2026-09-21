# 短边小于 720 隔离池

从 `data/` 移出、短边像素 `min(width, height) < 720`（不含 720）的图片。

目录结构与 `data/` 相同。稳定存量可迁 NAS：`cold/data_lt720/`（见 `NAS_MIRROR.md`）。

- **不参与**写对话取样（未用池仍是 `data/`）
- `data/_meta/index.jsonl` 对应行标 `"short_side_lt720": true`
- 校验：`.venv/bin/python scripts/validate_data_meta.py`
