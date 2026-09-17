# practical-mm-dialogue

实用多轮对话类图文数据集：真实图片 + 多轮图文对话样本的采集与标注流水线。

## 仓库里有什么

| 路径 | 说明 |
|------|------|
| `scripts/` | 采集、校验、生成、已用图归档脚本 |
| `prompts/qwen/` | 路由 / 分任务写作 / 修复提示词 |
| `data/_meta/index.jsonl` | 图片来源 / 许可 / `used` 标记 |
| `data/`、`data_used/` | **目录骨架与 README**（大体量实图不入库，见下） |
| `实用多轮对话类图文数据集/` | 任务与格式要求、样本 JSON + `samples/images` |

**实图策略：** `data/`（未用池）与 `data_used/`（已用池）中的 JPG/PNG 仅保留在本地，约 800MB+，不推送 GitHub。Clone 后请自行运行采集脚本补图。

## 质量分层（硬约定）

| 状态 | 含义 | 可否当金样 | 可否 `mark_images_used` |
|------|------|------------|-------------------------|
| `format_pass` | 仅过自动格式门禁 | 否 | 否（默认） |
| `human_pass` | 人工确认 OCR/贴图/深度 | 可晋升 | **是** |
| `rejected` | 人审淘汰 | 否 | 否 |

流程：`route → write → validate → repair → format_pass（进待审队列）→ 人审 → human_pass → mark_images_used`。

金样基准目前仅为 `000001`–`000004`；`format_pass` 联调样（如 `000010`–`000014`）须人审后再晋升。

## 快速开始

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r scripts/requirements.txt
cp .env.example .env   # Unsplash / DASHSCOPE_API_KEY
```

### 采集（示例）

```bash
.venv/bin/python scripts/fetch_sroie_receipts.py --limit 100
.venv/bin/python scripts/fetch_chartqa.py --limit 100
.venv/bin/python scripts/fetch_slidevqa.py --limit 100
.venv/bin/python scripts/fetch_wikimedia_work.py --limit 100
.venv/bin/python scripts/fetch_wikimedia_lifestyle.py --limit 100
```

### 千问生成完整样本（路由 → 写作 → 校验 → 修复）

默认 `--max-repair 3`；成功样本写入 `samples/` 并镜像到 `samples/_pending_review/`。

```bash
# 单批默认 5 图
.venv/bin/python scripts/generate_sample_qwen.py --model qwen3.5-flash

# 从 jsonl 批跑（可固定 sample_id）
.venv/bin/python scripts/generate_sample_qwen.py --batch-from-list scripts/examples/batch_jobs.example.jsonl

# 覆盖指定编号重跑
.venv/bin/python scripts/generate_sample_qwen.py --start-id 10 --paths 收据/xxx.jpg

.venv/bin/python scripts/validate_sample.py 实用多轮对话类图文数据集/samples/practical_mm_dialogue_000010.json
```

批跑结束会打印 `error_histogram_after_write` / `error_histogram_final`；token/耗时见 `logs/`。

### 人审队列与归档

```bash
.venv/bin/python scripts/list_pending_review.py
.venv/bin/python scripts/set_sample_qa_status.py 10 --status human_pass

.venv/bin/python scripts/validate_data_meta.py
# 默认只归档 human_pass 样本配图
.venv/bin/python scripts/mark_images_used.py --from-samples
# 紧急覆盖（不推荐）：
# .venv/bin/python scripts/mark_images_used.py --from-samples --allow-format-pass
```

写作对话时只从 `data/` 取未用图；**人审通过后再**移入 `data_used/`。

## 许可注意

各图片来源许可不同（SROIE、ChartQA、SlideVQA、Wikimedia、Unsplash 等），见 `data/_meta/index.jsonl` 与 `data/README.md`。二次分发前请逐条核对。
