"""存储源相关的三张表。列 = V1__Base_version.sql + V8 + V28__add_multi_user.sql。

    storage_source          一个存储源一行（类型、key、开关、排序）
    storage_source_config   存储源的参数行（name/value 键值对，如 filePath）
    user_storage_source     用户 × 存储源的授权：**三个维度挤在一行里**
                              enable       能不能看到这个存储源
                              permissions  看到之后能干什么（逗号分隔的 19 个操作）
                              root_path    能看到这个存储源的哪个子目录
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
    # DB 里存的是类型 key（"local"），不是枚举名（LOCAL）
    type: Mapped[str | None] = mapped_column(String(64))
    search_enable: Mapped[bool | None] = mapped_column(Boolean)
    search_ignore_case: Mapped[bool | None] = mapped_column(Boolean)
    order_num: Mapped[int | None] = mapped_column(Integer)
    default_switch_to_img_mode: Mapped[bool | None] = mapped_column(Boolean)
    remark: Mapped[str | None] = mapped_column(Text)
    # URL 的第一段就是它：http://ip:port/{key}/...
    key: Mapped[str | None] = mapped_column(String(64))
    # Java 里这两列已标 @Deprecated（权限迁移到 user_storage_source 了），保留列只为兼容老库
    enable_file_operator: Mapped[bool | None] = mapped_column(Boolean)
    search_mode: Mapped[str | None] = mapped_column(String(32))
    enable_file_anno_operator: Mapped[bool | None] = mapped_column(Boolean)
    compatibility_readme: Mapped[bool | None] = mapped_column(Boolean)


class StorageSourceConfig(Base):
    """存储源参数行：一行一个 key-value，如 (name='filePath', value='/data/storage')。

    Java 用反射把这堆行灌进 LocalParam 这类的对象；Pydantic 一句话搞定（见 loader.build_param）。
    """

    __tablename__ = "storage_source_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 参数名 = Pydantic param 的字段名（camelCase），如 filePath / proxyPrivate
    name: Mapped[str | None] = mapped_column(String(255))
    type: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(String(255))
    storage_id: Mapped[int | None] = mapped_column(Integer)
    # 值永远是字符串，类型转换是 param 模型的事（"true" -> True）
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
    # Java 侧是 Set<String> + CollectionStrTypeHandler（TypeHandler 负责跟逗号串互转）。
    # 我们保持 str，用到时 split(",") —— 步骤 5 只有 build_permission_map 一个使用点，
    # 不值得为它造一个自定义列类型。
    permissions: Mapped[str | None] = mapped_column(Text)
