# format_pass 镜像队列

自动生成且通过 `validate_sample` 的样本会：

1. 写入 `../practical_mm_dialogue_XXXXXX.json`（主副本）
2. 镜像到本目录（`review_queue=true`，`qa_status=format_pass`）

**`format_pass` ≠ 可出库。** 下一级是 **Agent 主审** → `agent_pass`（可 `mark_images_used` / 打交付包）。  
`human_pass` 仅给人抽检加签的金样子集，**不是**每条必经关。

`meta.ocr_spotcheck.api_ok=true` 只表示抽检 API 返回了 JSON，**`verified` 恒为 false**。

## 主流程

```
validate → format_pass（本目录）→ Agent 按 prompts/audit/agent_audit_rubric.md 出 jsonl
  → apply_agent_audit.py → agent_pass（批量出库）
  → 人只看 list_human_spotcheck（needs_human ∪ 约 10% agent_pass）
```

## 建议对照项（Agent 硬否决见 rubric）

- 创作：禁定稿回落；点名可见物禁近义替换
- 提取：列对齐、同格多值、店名/单号/结算对拍
- 推理：关键读数与图一致
- 实用问题：主体物件勿误认

```bash
.venv/bin/python scripts/list_pending_review.py
.venv/bin/python scripts/apply_agent_audit.py logs/agent_audit/<batch>.jsonl
.venv/bin/python scripts/list_human_spotcheck.py --sample-rate 0.1
# 可选金样加签：
# .venv/bin/python scripts/set_sample_qa_status.py 16 --status human_pass
.venv/bin/python scripts/mark_images_used.py --from-samples   # agent_pass 或 human_pass
```
