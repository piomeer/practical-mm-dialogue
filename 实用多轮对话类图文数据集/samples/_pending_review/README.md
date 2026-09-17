# format_pass 镜像队列

自动生成且通过 `validate_sample` 的样本会：

1. 写入 `../practical_mm_dialogue_XXXXXX.json`（主副本）
2. 镜像到本目录（`review_queue=true`，`qa_status=format_pass`）

**`format_pass` ≠ 金样。** `meta.ocr_spotcheck.api_ok=true` 只表示抽检 API 返回了 JSON，**`verified` 恒为 false**，不能当作 OCR 已正确。  
`key_numbers` 仅人审线索；硬门禁看 `core_keys`（单据头/结算字段须出现在 `answer`）。

本轮质量结论以 **Agent 对照原图的审核报告**为准（见 `logs/agent_audit_*.md`），不把「人审 → human_pass」作为必经阶段。

## 建议对照项（Agent / 抽查）

- 商户名 / 关键数字是否与图一致（`key_numbers` 线索；`core_keys` 须在 answer）
- `answer` 是否为末轮交付物本身
- 对话与 evidence 读数是否一致
- 报表行列是否对齐
- 是否未脱敏人名 / 图外发挥

```bash
.venv/bin/python scripts/list_pending_review.py
.venv/bin/python scripts/ocr_spotcheck_qwen.py --from-pending
# 可选后续能力（本轮不跑）：
# .venv/bin/python scripts/set_sample_qa_status.py 10 --status human_pass
# .venv/bin/python scripts/mark_images_used.py --from-samples
```
