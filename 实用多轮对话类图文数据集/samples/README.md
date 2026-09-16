# 真图测试样例

基于真实图片制作的 4 条测试样本。`samples/images/` 为样本侧副本（编号按样本内命名）。

对应源图已从 `data/` **移入** `data_used/`（未用池不再出现），meta 已标 `used: true`。

## 样本结构

| 样本 | 任务 | 图片 | 轮数 | 已归档源图（data_used） |
|------|------|------|------|-------------------------|
| `practical_mm_dialogue_000001.json` | 信息提取与整理 | `images/0001mcdonalds收据.jpg` | 4 | `收据/0001mcdonalds收据.jpg` |
| `practical_mm_dialogue_000002.json` | 信息提取与整理 | `images/0002mrdiy收据.jpg` | 4 | `收据/0002mrdiy收据.jpg` |
| `practical_mm_dialogue_000003.json` | 看图创作 | `0003沙滩救生塔.jpg` + `0004琵鹭湿地.jpg` | 6 | `生活场景/0001…` `0002…` |
| `practical_mm_dialogue_000004.json` | 看图创作 | `0005草坪野餐.jpg` + `0006西柚特写.jpg` | 6 | `生活场景/0003…` `0004…` |

- 两张收据各自独立成条，不做多图拼接。
- 场景图两两配对：海岸+湿地旅行系列；野餐+西柚生活方式种草。

## 后续写作流程

1. **只从 `data/` 取未用图**（不要用 `data_used/`）。
2. 样本写完后归档：

```bash
.venv/bin/python scripts/mark_images_used.py --paths 收据/00xx….jpg 生活场景/00xx….jpg
# 或
.venv/bin/python scripts/mark_images_used.py --from-samples
```

## 脱敏约定

- 对话与 `final_output` 中：个人姓名、电话号码做掩码（如 `***`、`03-****-****`）。
- 店名、品项、金额等任务必需信息保留。
- **源图文件本身未打码**（便于对照识读）；正式量产可另做图像脱敏。

## 阅读自检

打开任一 JSON 与对应图片，确认：

1. 没有图是否还能准确作答？（应不能）
2. 后一轮是否在前一轮上推进？
3. `final_output.answer` 是否等于对话收敛结果？
4. `<image>` 个数是否等于 `images` 长度且顺序一致？
