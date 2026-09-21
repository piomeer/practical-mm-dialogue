# NAS 镜像钩子（Agent / 人读）

SMB: `smb://192.168.31.13/家庭共享/实用多轮对话类图文数据集`

本目录本地池名：**`data_used`**（已用池）

对应 NAS 冷路径：`$NAS_ROOT/cold/data_used/`  
常见挂载：`/Volumes/家庭共享/实用多轮对话类图文数据集/cold/data_used/`

相对路径：本地 `data_used/收据/a.jpg` ↔ NAS `cold/data_used/收据/a.jpg`

查找顺序：本地有则用本地，否则去 NAS。勿将空目录当成无图。
