from app.models.config import SystemConfig
from app.models.storage import StorageSource, StorageSourceConfig, UserStorageSource
from app.models.user import User

# ⚠️ 这里的导入是**有副作用的**：import 一个模型类 = 把它注册进 Base.metadata。
# scripts/init_db.py 的 Base.metadata.create_all() 只认注册过的模型 ——
# 新加的模型忘了写进这里，表就会静默地不建，直到某天 select 报 "no such table"。
__all__ = [
    "SystemConfig",
    "StorageSource",
    "StorageSourceConfig",
    "UserStorageSource",
    "User",
]
