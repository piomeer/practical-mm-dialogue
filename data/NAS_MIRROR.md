# NAS 镜像钩子（Agent / 人读）

SMB: `smb://192.168.31.13/家庭共享/实用多轮对话类图文数据集`

本目录本地池名：**`data`**（未用池）

对应 NAS 冷路径：

```text
$NAS_ROOT/cold/data/
```

常见挂载：`/Volumes/家庭共享/实用多轮对话类图文数据集/cold/data/`

相对路径规则：本地 `data/收据/a.jpg` ↔ NAS `cold/data/收据/a.jpg`

## 查找顺序

1. 若本地本目录下该文件仍存在 → 用本地（采集可能正在写新图）
2. 否则 → 打开 NAS 上对应 `cold/data/<类别>/<文件名>`

勿把「本地目录看起来空」当成没有数据——稳定存量可能已迁到 NAS 腾盘。

`NAS_ROOT` 见仓库根 `.env` / `.env.example`。
