# 图片库目录说明

按任务类型分文件夹存放真实图片。

**暂停采集：** `学习材料/`、`代码报错/`（学习非必须；报错尚无合适批量源）。

## 未用 / 已用 / 短边隔离池

| 目录 | 含义 |
|------|------|
| `data/` | **未用池**：写对话、配对只从这里取图 |
| `data_used/` | **已用池**：样本写完后把对应图**移动**到此（分类结构与 `data/` 相同） |
| `data_lt720/` | **短边小于 720**：从 `data/` 移出，`min(w,h) < 720`（不含 720），结构同 `data/` |

`data/_meta/index.jsonl` 中对应行会标 `"used": true` 或 `"short_side_lt720": true`，`source_id` 保留，采集脚本不会重复下载。

```bash
# 按路径归档
.venv/bin/python scripts/mark_images_used.py --paths 收据/0003sroie_xxx.jpg 生活场景/0005xxx.jpg

# 或根据 samples/*.json 文件名自动匹配并归档
.venv/bin/python scripts/mark_images_used.py --from-samples
```

## 采集策略（重要）

| 类型 | 主力源 | 补充源 |
|------|--------|--------|
| 工作/生活场景图 | **Wikimedia Commons** | Unsplash、**Pexels（size=large）** |
| 收据 | ICDAR2019-SROIE | **CORD v2** |
| 图表推理 | **PlotQA**（优先高清） | ChartQA（多数短边不足，易进 lt720） |
| 文档截图 | SlideVQA | **DocLayNet-v1.2**、**DocVQA**、**InfographicVQA** |
| 代码报错 | 后续自采 | — |

**不要用 CharXiv 入库：** 官方仅允许评估、禁止训练；图版权属 arXiv 原作者。

**不要把 Unsplash 当场景图主力**（Demo 配额小）；批量补场景优先 Pexels / Wikimedia。

## 命名与元数据

文件夹内四位编号 + 短名。`source` 常见值：`wikimedia` / `unsplash` / `pexels` / `sroie` / `cord_v2` / `chartqa` / `plotqa` / `slidevqa` / `doclaynet` / `docvqa` / `infographicvqa` / `manual`。

## 场景图：Wikimedia（主力）

```bash
.venv/bin/python scripts/fetch_wikimedia_work.py --limit 100      # → 工作场景/
.venv/bin/python scripts/fetch_wikimedia_lifestyle.py --limit 100 # → 生活场景/
```

- 只保留 CC0 / Public Domain / CC-BY（排除 NC）
- 请遵守 Commons 礼貌限速；遇 429 增大 `--sleep`

## 场景图：Pexels（高清补充，推荐）

```bash
.venv/bin/python scripts/fetch_pexels_lifestyle.py --limit 20 --per-page 40 --sleep 0.5
.venv/bin/python scripts/fetch_pexels_work.py --limit 20 --per-page 40 --sleep 0.5
```

需 `.env` 中 `PEXELS_API_KEY`（https://www.pexels.com/api/）。默认 `size=large`、`--min-short-side 720`。

## 场景图：Unsplash（补充）

```bash
.venv/bin/python scripts/fetch_unsplash_lifestyle.py --limit 20 --per-page 30 --sleep 1.0
.venv/bin/python scripts/fetch_unsplash_work.py --limit 20 --per-page 30 --sleep 1.0
```

需 `.env` 中 `UNSPLASH_ACCESS_KEY`。Demo 约 50 次请求/小时。

## 收据：SROIE / CORD v2

```bash
.venv/bin/python scripts/fetch_sroie_receipts.py --limit 100 --split train
.venv/bin/python scripts/fetch_cord_v2.py --limit 100 --split train --min-short-side 720
```

## 图表：PlotQA（优先）/ ChartQA

```bash
# PlotQA 原图短边多在 600–719，默认 --min-short-side 600
.venv/bin/python scripts/fetch_plotqa.py --limit 100 --split validation --min-short-side 600
.venv/bin/python scripts/fetch_chartqa.py --limit 100 --split train
```

## 文档：SlideVQA / DocLayNet / DocVQA / InfographicVQA

```bash
.venv/bin/python scripts/fetch_slidevqa.py --limit 100
.venv/bin/python scripts/fetch_doclaynet.py --limit 100 --split validation --min-short-side 720
.venv/bin/python scripts/fetch_docvqa.py --limit 50 --config DocVQA --split validation
.venv/bin/python scripts/fetch_docvqa.py --limit 50 --config InfographicVQA --split validation
```

DocLayNet 使用可流式的 `docling-project/DocLayNet-v1.2`（勿用已废弃的 DocLayNet.py 脚本数据集）。可选在 `.env` 设置 `HF_TOKEN` 提高 Hugging Face 限速。

## 校验

```bash
.venv/bin/python scripts/validate_data_meta.py
# 分别统计 data/、data_used/、data_lt720/；short_side_lt720=true 应在 data_lt720/
```
