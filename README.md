# practical-mm-dialogue

实用多轮对话类图文数据集：真实图片 + 多轮图文对话样本的采集与标注流水线。

## 仓库里有什么

| 路径 | 说明 |
|------|------|
| `scripts/` | 采集、校验、已用图归档脚本 |
| `data/_meta/index.jsonl` | 图片来源 / 许可 / `used` 标记 |
| `data/`、`data_used/` | **目录骨架与 README**（大体量实图不入库，见下） |
| `实用多轮对话类图文数据集/` | 任务与格式要求、4 条合格样本 JSON + `samples/images` |

**实图策略：** `data/`（未用池）与 `data_used/`（已用池）中的 JPG/PNG 仅保留在本地，约 800MB+，不推送 GitHub。Clone 后请自行运行采集脚本补图。

## 快速开始

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r scripts/requirements.txt
cp .env.example .env   # 如需 Unsplash 补充源，填入 Access Key
```

### 采集（示例）

```bash
.venv/bin/python scripts/fetch_sroie_receipts.py --limit 100
.venv/bin/python scripts/fetch_chartqa.py --limit 100
.venv/bin/python scripts/fetch_slidevqa.py --limit 100
.venv/bin/python scripts/fetch_wikimedia_work.py --limit 100
.venv/bin/python scripts/fetch_wikimedia_lifestyle.py --limit 100
```

### 校验 / 归档已用图

```bash
.venv/bin/python scripts/validate_data_meta.py
.venv/bin/python scripts/mark_images_used.py --paths 收据/00xx.jpg
# 或根据 samples 自动匹配
.venv/bin/python scripts/mark_images_used.py --from-samples
```

写作对话时只从 `data/` 取未用图；写完后移入 `data_used/`。

## 许可注意

各图片来源许可不同（SROIE、ChartQA、SlideVQA、Wikimedia、Unsplash 等），见 `data/_meta/index.jsonl` 与 `data/README.md`。二次分发前请逐条核对。
