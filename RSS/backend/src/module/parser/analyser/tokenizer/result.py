"""种子标题解析的领域结果模型。

tokenizer 刻意把缺失值保持为 ``None``：像「缺省 season=1 / episode=0」这类
业务默认值是上层（release_policy / title_parser）的职责，解析器本身只记录
证据，不做缺省填充。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class MediaType(StrEnum):
    """发行物代表的媒体类型。"""

    UNKNOWN = "unknown"
    EPISODE = "episode"
    MOVIE = "movie"
    OVA = "ova"
    OAD = "oad"
    SPECIAL = "special"
    PV = "pv"
    OPENING = "opening"
    ENDING = "ending"


class ReleaseKind(StrEnum):
    """发行物的集数基数，与媒体类型正交（单集 / 区间 / 季度全集 / 合集）。"""

    SINGLE = "single"
    RANGE = "range"
    BATCH = "batch"
    COLLECTION = "collection"


@dataclass(frozen=True, slots=True)
class ParsedRelease:
    """结构化、保真的资源名解析结果。"""

    raw: str
    title_en: str | None = None
    title_zh: str | None = None
    title_jp: str | None = None
    group: str | None = None
    season: int | None = None
    season_raw: str | None = None
    episode: int | float | None = None
    episode_end: int | float | None = None
    episode_title: str | None = None
    media_type: MediaType = MediaType.UNKNOWN
    release_kind: ReleaseKind = ReleaseKind.SINGLE
    resolution: str | None = None
    source: str | None = None
    subtitle: str | None = None
    codecs: tuple[str, ...] = ()
    audio: tuple[str, ...] = ()
    container: str | None = None
    version: int | None = None
    year: int | None = None
    tags: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()

    @property
    def primary_title(self) -> str | None:
        """取最可用的标题，不套用语言偏好策略。"""
        return self.title_en or self.title_zh or self.title_jp

    @property
    def is_movie(self) -> bool:
        return self.media_type is MediaType.MOVIE

    @property
    def is_mixed_collection(self) -> bool:
        """合集但无法归为单一媒体类型（如混合了 TV+剧场版的特典包）。"""
        return (
            self.media_type is MediaType.UNKNOWN
            and self.release_kind is ReleaseKind.COLLECTION
        )
