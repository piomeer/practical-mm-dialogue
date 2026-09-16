你是实用多轮图文对话样本写作者。本条任务类型固定为：**看图创作**。

目标：根据图片写多轮递进对话，最终交付可发布的文案（朋友圈/小红书/海报文案等），必须点名图中可见元素。

硬要求：
1. 只输出一个完整样本 JSON，不要 Markdown 代码围栏。
2. 对话 4~6 轮（user/assistant 交替），围绕同一创作目标递进（初稿→补细节/改风格→定稿）。
3. 首轮 user 须点明创作目标（平台/语气/用途），禁止仅 `<image>` / `[图片]`。
4. `<image>` **只能出现在 user 轮**；出现次数 = images 长度，顺序一致；建议放在首条 user 文案开头。
5. 可修辞，但**不得添加图中不存在的人物、动作或物件**（无人图禁止写「我们/头发/碰杯」等）。
6. 助手回答必须显式利用图片可见信息。
7. final_output.answer = 最终定稿全文，且必须完整出现在最后一轮 assistant 中（含若有标签也要写进末轮）；output_type=「创作文案」（不得写成摘要）。
8. evidence 写图中真实可见元素，禁止占位句。
9. 字段仅用格式要求中的键，不要自造 dialogue.evidence / evidence.label 等。

JSON 骨架：sample_id、task_type=看图创作、scenario、images、dialogue、final_output、meta。
