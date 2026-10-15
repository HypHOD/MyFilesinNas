from typing import Optional

from sqlmodel import Field, SQLModel


class Bangumi(SQLModel, table=True):
    """番剧订阅规则"""

    id: int = Field(default=None, primary_key=True)
    official_title: str = Field(default="official_title", title="番剧中文名")
    year: Optional[str] = Field(default=None, title="番剧年份")
    title_raw: str = Field(default="title_raw", title="番剧原名", index=True)
    season: int = Field(default=1, title="番剧季度")
    season_raw: Optional[str] = Field(default=None, title="番剧季度原名")
    group_name: Optional[str] = Field(default=None, title="字幕组")
    dpi: Optional[str] = Field(default=None, title="分辨率")
    source: Optional[str] = Field(default=None, title="来源")
    subtitle: Optional[str] = Field(default=None, title="字幕")
    episode_offset: int = Field(default=0, title="集数偏移量")
    season_offset: int = Field(default=0, title="季度偏移量")
    filter: str = Field(default="720,\\d+-\\d+", title="番剧过滤器")
    rss_link: str = Field(default="", title="番剧 RSS 链接")
    poster_link: Optional[str] = Field(default=None, title="番剧海报链接")
    added: bool = Field(default=False, title="规则是否已添加")
    rule_name: Optional[str] = Field(default=None, title="下载器规则名")
    save_path: Optional[str] = Field(default=None, title="保存路径")
    deleted: bool = Field(default=False, title="是否已删除", index=True)
    archived: bool = Field(default=False, title="是否已归档", index=True)
    air_weekday: Optional[int] = Field(default=None, title="放送星期（0=周一）")
    episode_type: str = Field(default="episode", title="剧集类型 episode|movie|special")


class BangumiUpdate(SQLModel):
    """番剧部分更新载荷：只应用显式提供的字段。"""

    official_title: Optional[str] = None
    year: Optional[str] = None
    title_raw: Optional[str] = None
    season: Optional[int] = None
    season_raw: Optional[str] = None
    group_name: Optional[str] = None
    dpi: Optional[str] = None
    source: Optional[str] = None
    subtitle: Optional[str] = None
    episode_offset: Optional[int] = None
    season_offset: Optional[int] = None
    filter: Optional[str] = None
    rss_link: Optional[str] = None
    poster_link: Optional[str] = None
    added: Optional[bool] = None
    rule_name: Optional[str] = None
    save_path: Optional[str] = None
    archived: Optional[bool] = None
    air_weekday: Optional[int] = None
    episode_type: Optional[str] = None
