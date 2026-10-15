from typing import Optional

from sqlmodel import Field, SQLModel


class RSSItem(SQLModel, table=True):
    """RSS 订阅源
    默认设置为蜜柑
    """

    id: int = Field(default=None, primary_key=True)
    name: Optional[str] = Field(default=None, title="订阅源名称")
    url: str = Field(default="https://mikanani.me", title="订阅源地址", index=True)
    aggregate: bool = Field(default=False, title="是否解析种子发现新番")
    parser: str = Field(default="mikan", title="解析器类型")
    enabled: bool = Field(default=True, title="是否启用")
    connection_status: Optional[str] = Field(default=None, title="连接状态")
    last_checked_at: Optional[str] = Field(default=None, title="最后检查时间")
    last_error: Optional[str] = Field(default=None, title="最后错误信息")


class RSSUpdate(SQLModel):
    """RSS 部分更新载荷：只应用显式提供的字段。"""

    name: Optional[str] = None
    url: Optional[str] = None
    aggregate: Optional[bool] = None
    parser: Optional[str] = None
    enabled: Optional[bool] = None
