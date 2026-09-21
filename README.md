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

**实图策略：** `data/`（未用池）与 `data_used/`（已用池）中的 JPG/PNG **默认不推送 GitHub**。本地盘紧张时，稳定存量迁到 NAS 冷存；采集仍可继续写本地新图。

### NAS 冷存（腾盘）

- SMB：`smb://192.168.31.13/家庭共享/实用多轮对话类图文数据集`
- `.env`：`NAS_ROOT=/Volumes/家庭共享/实用多轮对话类图文数据集`
- 布局：`$NAS_ROOT/cold/{data,data_used,data_lt720}/`
- 钩子：各池 `NAS_MIRROR.md` / `.nas_root`；Cursor 规则 `.cursor/rules/nas-image-pools.mdc`
- 查找：本地有文件用本地，否则去 NAS 对应 `cold/<pool>/`

```bash
# 干跑：预览将迁走的稳定文件（默认跳过最近 45 分钟内修改的文件，避免撞采集）
.venv/bin/python scripts/nas_migrate_stable.py --dry-run

# 腾盘迁移（**请在本机 Terminal.app 执行**；Cursor 沙箱无法写入 /Volumes SMB）
./scripts/run_nas_migrate_in_terminal.sh --dry-run
./scripts/run_nas_migrate_in_terminal.sh

# 重建图账本（untouched / processed_unqualified / qualified；合格=agent_pass|human_pass）
.venv/bin/python scripts/rebuild_image_inventory.py --also-nas-ledger
```

## 质量分层（硬约定）

| 状态 | 含义 | 可否出库 / 交付 | 可否 `mark_images_used` |
|------|------|-----------------|-------------------------|
| `format_pass` | 仅过自动格式门禁 | 否 | 否（默认） |
| `agent_pass` | **Agent 对照原图主审通过** | **是**（吞吐层） | **是** |
| `human_pass` | 人抽检/加签金样 | 是（金样子集） | 是 |
| `rejected` | 淘汰 | 否 | 否 |

主流程：`route → write → validate → repair → format_pass → Agent 主审（rubric + jsonl）→ agent_pass → mark_images_used / 交付`。

人工**不**再全量逐条审核；只处理 `needs_human` 与对 `agent_pass` 的抽样（见 `list_human_spotcheck.py`）。规范：`prompts/audit/agent_audit_rubric.md`。

收据/文档会附带 `meta.ocr_spotcheck`：`key_numbers` 仅线索；硬门禁看 `core_keys`。`api_ok≠verified`。

金样基准 `000001`–`000004` 仍为 `human_pass`；大批量新样以 `agent_pass` 出库即可。


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

### Agent 主审、人抽检与归档

```bash
# format_pass 队列（线索列表）
.venv/bin/python scripts/list_pending_review.py

# Agent 按 prompts/audit/agent_audit_rubric.md 写出 jsonl 后一键晋升
.venv/bin/python scripts/apply_agent_audit.py logs/agent_audit/<batch>.jsonl

# 人抽检：全部 needs_human + 约 10% agent_pass
.venv/bin/python scripts/list_human_spotcheck.py --sample-rate 0.1

# 可选：抽检确认后加签金样
.venv/bin/python scripts/set_sample_qa_status.py 16 --status human_pass

.venv/bin/python scripts/validate_data_meta.py
# 默认归档 agent_pass 与 human_pass 样本配图
.venv/bin/python scripts/mark_images_used.py --from-samples
# 紧急覆盖（不推荐）：
# .venv/bin/python scripts/mark_images_used.py --from-samples --allow-format-pass
```

写作对话时只从 `data/` 取未用图；**Agent 主审（或人加签）通过后再**移入 `data_used/`。


## 许可注意

各图片来源许可不同（SROIE、ChartQA、SlideVQA、Wikimedia、Unsplash 等），见 `data/_meta/index.jsonl` 与 `data/README.md`。二次分发前请逐条核对。
