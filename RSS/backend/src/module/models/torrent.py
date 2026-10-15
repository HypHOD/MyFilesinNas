from typing import Optional

from pydantic import BaseModel
from pydantic import Field as PydanticField
from sqlmodel import Field, SQLModel


class Torrent(SQLModel, table=True):
    """已投递的种子记录（去重与追溯的依据）"""

    id: int = Field(default=None, primary_key=True)
    bangumi_id: Optional[int] = Field(
        default=None, foreign_key="bangumi.id", index=True, title="关联番剧"
    )
    rss_id: Optional[int] = Field(
        default=None, foreign_key="rssitem.id", index=True, title="来源 RSS"
    )
    name: str = Field(default="", title="种子名称")
    url: str = Field(
        default="https://example.com/torrent", title="种子地址", index=True
    )
    homepage: Optional[str] = Field(default=None, title="详情页地址")
    downloaded: bool = Field(default=False, title="是否已下载")
    qb_hash: Optional[str] = Field(default=None, title="下载器 hash", index=True)


class EpisodeFile(BaseModel):
    """重命名环节解析出的媒体文件（对应下载器内的文件路径）。"""

    media_path: str
    group: Optional[str] = None
    title: str
    season: int
    episode: int | float | None = None
    suffix: str = PydanticField(pattern=r"\.(mkv|mp4|MKV|MP4)$")
    episode_type: str = "episode"  # episode | movie | special


class SubtitleFile(BaseModel):
    """重命名环节解析出的字幕文件。"""

    media_path: str
    group: Optional[str] = None
    title: str
    season: int
    episode: int | float | None = None
    language: str = PydanticField(pattern=r"^(zh|zh-tw)$")
    suffix: str = PydanticField(pattern=r"\.(ass|srt|ASS|SRT)$")
    episode_type: str = "episode"  # episode | movie | special
