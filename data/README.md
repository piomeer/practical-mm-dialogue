# 图片库目录说明

按任务类型分文件夹存放真实图片。

**暂停采集：** `学习材料/`、`代码报错/`（学习非必须；报错尚无合适批量源）。

## 未用 / 已用池

| 目录 | 含义 |
|------|------|
| `data/` | **未用池**：写对话、配对只从这里取图 |
| `data_used/` | **已用池**：样本写完后把对应图**移动**到此（分类结构与 `data/` 相同） |

`data/_meta/index.jsonl` 中对应行会标 `"used": true`，`source_id` 保留，采集脚本不会重复下载。

```bash
# 按路径归档
.venv/bin/python scripts/mark_images_used.py --paths 收据/0003sroie_xxx.jpg 生活场景/0005xxx.jpg

# 或根据 samples/*.json 文件名自动匹配并归档
.venv/bin/python scripts/mark_images_used.py --from-samples
```

## 采集策略（重要）

| 类型 | 主力源 | 补充源 |
|------|--------|--------|
| 工作/生活场景图 | **Wikimedia Commons**（开放许可、可批量） | Unsplash API（Demo 约 50 次/小时，仅补缺） |
| 收据 | ICDAR2019-SROIE | 手动票 |
| 图表推理 | ChartQA | — |
| 文档截图 | SlideVQA（VisRAG corpus） | — |
| 代码报错 | 后续自采 | — |

**不要把 Unsplash 当场景图主力。**

## 目录现状（各约 500 已达成）

| 文件夹 | 张数 | 用途 | 当前来源 |
|--------|------|------|----------|
| `生活场景/` | ~502 未用（+4 已用） | 看图创作 / 生活实用 | Wikimedia（主）+ Unsplash（少） |
| `工作场景/` | ~500 未用 | 看图创作 / 工作实用 | Wikimedia Commons |
| `收据/` | ~498 未用（+2 已用） | 信息提取 | SROIE |
| `文档截图/` | ~500 未用 | 提取 / 翻译 | SlideVQA |
| `图表推理/` | ~500 未用 | 逻辑推理 | ChartQA |
| `学习材料/` | 0 | 翻译 / 学习 | **暂停** |
| `代码报错/` | 0 | 代码 debug | **暂停** |
| `_meta/` | — | 来源与许可索引 | `index.jsonl`（含 `used`） |

**结论：** 上述五类用现有源即可撑到 500，暂不需要新开数据源。学习材料 / 代码报错若恢复采集再另选源。

## 命名与元数据

文件夹内四位编号 + 短名。`source`：`wikimedia` / `unsplash` / `sroie` / `chartqa` / `slidevqa` / `manual`。

## 场景图：Wikimedia（主力）

```bash
.venv/bin/python scripts/fetch_wikimedia_work.py --limit 100      # → 工作场景/
.venv/bin/python scripts/fetch_wikimedia_lifestyle.py --limit 100 # → 生活场景/
```

- 只保留 CC0 / Public Domain / CC-BY（排除 NC）
- 请遵守 Commons 礼貌限速；遇 429 增大 `--sleep`

## 场景图：Unsplash（补充）

```bash
.venv/bin/python scripts/fetch_unsplash_lifestyle.py --limit 20
.venv/bin/python scripts/fetch_unsplash_work.py --limit 20
```

需 `.env` 中 `UNSPLASH_ACCESS_KEY`；Demo 配额很小。

## SROIE → 收据

```bash
.venv/bin/python scripts/fetch_sroie_receipts.py --limit 100 --split train
```

## ChartQA → 图表推理

```bash
.venv/bin/python scripts/fetch_chartqa.py --limit 100 --split train
```

## SlideVQA → 文档截图

```bash
.venv/bin/python scripts/fetch_slidevqa.py --limit 100
```

## 校验

```bash
.venv/bin/python scripts/validate_data_meta.py
# 会分别统计 data/（未用）与 data_used/（已用）；used=true 的文件应在 data_used/
```
