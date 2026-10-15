"""解析结果 → 番剧订阅的业务转换。

参考实现的 LLM / TMDB / 海报抓取在本工程全部裁剪，raw_parser 是同步
纯函数：classic 解析 → 准入策略 → 标题语言回退 → Bangumi 模型。
"""

import logging

from module.conf import settings
from module.models import Bangumi
from module.parser.analyser.raw_parser import raw_parser as release_parser
from module.parser.analyser.tokenizer import ParsedRelease
from module.parser.release_policy import (
    bangumi_episode_type,
    normalized_season,
    persistence_target,
)

logger = logging.getLogger(__name__)


class TitleParser:
    @staticmethod
    def _resolve_titles(release: ParsedRelease) -> tuple[str | None, str | None]:
        """按配置首选语言解析 official_title / title_raw。

        official_title 回退链：配置语言 → zh → en → jp；
        title_raw 固定取 en → zh → jp（第一优先级总是罗马字原名）。
        """
        language = settings.rss_parser.language
        titles = {
            "zh": release.title_zh,
            "en": release.title_en,
            "jp": release.title_jp,
        }
        title_raw = release.title_en or release.title_zh or release.title_jp
        if titles[language]:
            official_title = titles[language]
        elif titles["zh"]:
            official_title = titles["zh"]
        elif titles["en"]:
            official_title = titles["en"]
        elif titles["jp"]:
            official_title = titles["jp"]
        else:
            official_title = title_raw
        return official_title, title_raw

    @staticmethod
    def _release_to_bangumi(
        release: ParsedRelease, official_title: str, title_raw: str
    ) -> Bangumi:
        return Bangumi(
            official_title=official_title,
            title_raw=title_raw,
            year=str(release.year) if release.year is not None else None,
            season=normalized_season(release),
            season_raw=release.season_raw,
            group_name=release.group or "",
            dpi=release.resolution,
            source=release.source,
            subtitle=release.subtitle,
            episode_offset=0,
            filter=",".join(settings.rss_parser.filter),
            episode_type=bangumi_episode_type(release),
        )

    @staticmethod
    def raw_parser(raw: str) -> Bangumi | None:
        """资源名 → 番剧订阅；解析失败或准入拒绝返回 None。"""
        try:
            release = release_parser(raw)
            if release is None:
                return None
            if persistence_target(release) is None:
                logger.debug("Parsed but did not admit resource: %s", raw)
                return None
            official_title, title_raw = TitleParser._resolve_titles(release)
            if not title_raw:
                logger.warning("Cannot extract title_raw from '%s', skipping", raw)
                return None
            if not official_title:
                logger.warning("Cannot extract official_title from '%s', skipping", raw)
                return None
            logger.debug("RAW:%s >> %s", raw, title_raw)
            return TitleParser._release_to_bangumi(release, official_title, title_raw)
        except (ValueError, AttributeError, TypeError) as e:
            logger.warning(f"Cannot parse '{raw}': {type(e).__name__}: {e}")
            return None
