# Agent 主审规范（执行 Agent 必读）

对照原图审核 `format_pass` 样本。输出必须写入 `logs/agent_audit/<batch_id>.jsonl`（每样本一行 JSON），**禁止只写散文报告代替结构化 verdict**。

## 判定枚举（必选其一）

| verdict | 含义 | 脚本行为（`apply_agent_audit.py`） |
|---------|------|-----------------------------------|
| `pass` | 对照原图合格 | → `qa_status=agent_pass`，清 pending |
| `fail` | 硬伤，不可出库 | 保持 `format_pass`（或 `--reject-fails` 时 `rejected`），写入 `meta.agent_audit` |
| `needs_human` | 关键存疑 | 保持 `format_pass`，`human_spot_queue=true` |

**禁止**使用「建议通过（有保留）」「大体对齐」等模糊措辞作为最终 verdict。有硬伤必须 `fail`；仅当图糊到无法对拍关键字段时用 `needs_human`。

## 通用检查（所有任务）

1. `validate_sample --check-files` 已通过（否则先修格式，不进主审）。
2. `answer` 为末轮交付主体（文案 / 表 / 行动计划 / 推理结论）。
3. evidence 与 `answer` 不自相矛盾（evidence 写到的关键数字须能在 answer 中找到或明确不要求入表）。
4. 无未脱敏人名（收据类）；无伪 `<image>` 标记。

## 按任务类型：硬否决

### 看图创作

- **定稿回落 = fail**：若用户说「确认这个版本 / 就用上一版」等，末轮与 `answer` 必须覆盖**上一助手轮**强化稿的要点词（菜单名、点名物件、用户刚要求的细节）。回到更早初稿 → **fail**。
- 用户点名且图中可见的物件：定稿必须出现原词，**禁止近义替换**（蓝莓→野草莓）→ 否则 fail。
- 图外物件可轻度修辞，但不得当主卖点硬编；明显幻觉（风铃等图中无）→ fail。

### 信息提取与整理

- 报表列须与图列对应；**自造「备注」列吞掉本属某列的数字** → fail。
- 同格多值（如 `15.0%` + `+60 bps`）必须同列，漏次要值 → fail。
- 店名 / 单据号 / 结算关键字段与图不一致 → fail（难辨认则 `needs_human`）。
- `ocr_spotcheck.verified` 恒为 false，**不得**因 `api_ok=true` 判 pass。

### 逻辑推理

- 对话与 evidence 中关键年份/系列读数必须与图一致；偏差（如 37→40）→ fail。
- 可拒答图外因果，但不许改数。

### 生活/工作/学习实用问题

- 主体结构/家具须贴图正确（勿把打字机写成电报机、球灯写成吊扇灯）→ 误认 fail。
- 方案外延（增购设备）可接受，但不得把外延说成图中已有。

### 文档翻译 / 其它

- 译文须对应图中可见文字块；明显整段臆造 → fail。

## jsonl 行 schema

```json
{
  "sample_id": "practical_mm_dialogue_000016",
  "verdict": "pass",
  "task_type": "生活/工作/学习实用问题",
  "reasons": ["吊灯/打字机已纠正", "行动计划完整"],
  "critical_checks": {
    "draft_rollback": "n/a",
    "ocr_fields": "n/a",
    "chart_readings": "n/a",
    "object_grounding": "ok"
  }
}
```

`critical_checks` 取值建议：`ok` / `fail` / `n/a` / `unsure`（unsure 时 verdict 应为 `needs_human` 或 `fail`，不要 `pass`）。

## 推荐命令

```bash
# Agent 写完 jsonl 后一键晋升
.venv/bin/python scripts/apply_agent_audit.py logs/agent_audit/<batch_id>.jsonl

# 人抽检清单：全部 needs_human + 10% agent_pass
.venv/bin/python scripts/list_human_spotcheck.py --sample-rate 0.1
```
