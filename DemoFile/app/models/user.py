from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

# 对应 Java 的 UserConstant：没有角色表，id 就是角色
NEW_USER_TEMPLATE_ID = 0
ADMIN_ID = 1
ANONYMOUS_ID = 2


class User(Base):
    """user 表。形状 = V28__add_multi_user.sql + V36 加的 salt 列。

    id 的约定（没有角色表，全靠这几个常量）：
      0 = 新建用户的模板行
      1 = 管理员
      2 = 匿名访客（guest）
    """

    __tablename__ = "user"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str | None] = mapped_column(String(255))
    nickname: Mapped[str | None] = mapped_column(String(255))
    password: Mapped[str | None] = mapped_column(String(32))
    enable: Mapped[bool | None] = mapped_column(Boolean)
    create_time: Mapped[datetime | None] = mapped_column(DateTime)
    update_time: Mapped[datetime | None] = mapped_column(DateTime)
    # 逗号分隔的权限串，如 "createShareLink,customShareKey"
    default_permissions: Mapped[str | None] = mapped_column(Text)
    salt: Mapped[str | None] = mapped_column(String(32))
