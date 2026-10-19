"""存储源相关的三张表。列定义对应 V1__Base_version.sql + V8 + V28__add_multi_user.sql。

    storage_source          一个存储源一行（类型、key、开关、排序）
    storage_source_config   存储源参数行（name/value 键值对，如 filePath）
    user_storage_source     用户 × 存储源授权，三个维度在同一行：
                              enable       是否可见
                              permissions  可见后的操作权限（逗号分隔的 19 个操作）
                              root_path    可见的子目录
"""

from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class StorageSource(Base):
    __tablename__ = "storage_source"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    enable: Mapped[bool | None] = mapped_column(Boolean)
    enable_cache: Mapped[bool | None] = mapped_column(Boolean)
    name: Mapped[str | None] = mapped_column(String(255))
    auto_refresh_cache: Mapped[bool | None] = mapped_column(Boolean)
    # 数据库中存的是类型 key（"local"），不是枚举名（LOCAL）。
    type: Mapped[str | None] = mapped_column(String(64))
    search_enable: Mapped[bool | None] = mapped_column(Boolean)
    search_ignore_case: Mapped[bool | None] = mapped_column(Boolean)
    order_num: Mapped[int | None] = mapped_column(Integer)
    default_switch_to_img_mode: Mapped[bool | None] = mapped_column(Boolean)
    remark: Mapped[str | None] = mapped_column(Text)
    # URL 的第一段：http://ip:port/{key}/...
    key: Mapped[str | None] = mapped_column(String(64))
    # Java 中这两列已标 @Deprecated（权限已迁移到 user_storage_source），保留仅为兼容旧库。
    enable_file_operator: Mapped[bool | None] = mapped_column(Boolean)
    search_mode: Mapped[str | None] = mapped_column(String(32))
    enable_file_anno_operator: Mapped[bool | None] = mapped_column(Boolean)
    compatibility_readme: Mapped[bool | None] = mapped_column(Boolean)


class StorageSourceConfig(Base):
    """存储源参数行：一行一个 key-value，如 (name='filePath', value='/data/storage')。

    Java 通过反射将这些行填入 LocalParam 等对象；这里由 loader.build_param 用
    Pydantic 构造。
    """

    __tablename__ = "storage_source_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 参数名对应 Pydantic param 的字段名（camelCase），如 filePath / proxyPrivate。
    name: Mapped[str | None] = mapped_column(String(255))
    type: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(String(255))
    storage_id: Mapped[int | None] = mapped_column(Integer)
    # 值始终是字符串，类型转换由 param 模型完成（"true" -> True）。
    value: Mapped[str | None] = mapped_column(Text)


class UserStorageSource(Base):
    __tablename__ = "user_storage_source"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(Integer)
    storage_source_id: Mapped[int | None] = mapped_column(Integer)
    root_path: Mapped[str | None] = mapped_column(Text)
    enable: Mapped[bool | None] = mapped_column(Boolean)
    # 逗号分隔的操作名串，如 "available,newFolder,upload,..."
    #
    # Java 侧是 Set<String> + CollectionStrTypeHandler（负责与逗号串互转）。
    # 这里保持 str，使用时 split(",")；目前只有 build_permission_map 一个使用点，
    # 不值得引入自定义列类型。
    permissions: Mapped[str | None] = mapped_column(Text)
