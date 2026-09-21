# NAS 镜像钩子（样本配图目录）

本目录是**样本绑定镜像**（`samples/images/`），通常仍保留在本地以便 validate。

源图冷存按类别在 NAS：

- `$NAS_ROOT/cold/data/<类别>/`
- `$NAS_ROOT/cold/data_used/<类别>/`
- `$NAS_ROOT/cold/data_lt720/<类别>/`

SMB: `smb://192.168.31.13/家庭共享/实用多轮对话类图文数据集`

查找源图：先看样本 JSON 的 `meta.source_paths`，再按池在本地或 NAS `cold/<pool>/` 解析。
