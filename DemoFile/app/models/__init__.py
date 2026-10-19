from app.models.config import SystemConfig
from app.models.storage import StorageSource, StorageSourceConfig, UserStorageSource
from app.models.user import User

# 这些导入有副作用：import 模型类会将其注册进 Base.metadata。
# scripts/init_db.py 的 Base.metadata.create_all() 只创建已注册的模型；
# 新增模型若未加入这里，表不会创建，直到查询时报 "no such table"。
__all__ = [
    "SystemConfig",
    "StorageSource",
    "StorageSourceConfig",
    "UserStorageSource",
    "User",
]
