"""RSS 自动发现新番：把源里的未知条目解析成订阅条目。

镜像参考实现的 RSSAnalyser 做减法：砍掉 TMDB / mikan 主页海报抓取、
Movie 分支、单条入口（torrent_to_data / link_to_data）与多引擎快照；
只保留 aggregate 源「扫描 → 建订阅」这一条主路径。
"""

import logging
import re

from module.database.bangumi import match_bangumi_in_list
from module.models import Bangumi, RSSItem, Torrent
from module.network import RequestContent
from module.parser import TitleParser

from .engine import RSSEngine

logger = logging.getLogger(__name__)


class RSSAnalyser:
    @staticmethod
    async def get_rss_torrents(rss_link: str, full_parse: bool = True) -> list[Torrent]:
        """拉取源条目；full_parse=False 时只保留区间条目（如 ``[01-12]``）。"""
        async with RequestContent() as req:
            if full_parse:
                rss_torrents = await req.get_torrents(rss_link)
            else:
                rss_torrents = await req.get_torrents(rss_link, "\\d+-\\d+")
        return rss_torrents

    async def torrents_to_data(
        self, torrents: list[Torrent], rss: RSSItem
    ) -> list[Bangumi]:
        """逐条解析成订阅条目；以 ``(title_raw, season)`` 做批内去重。

        同一番剧的多集条目解析出的 title_raw/season 相同，只保留首条。
        """
        new_bangumi: list[Bangumi] = []
        seen_identities: set[tuple[str, int]] = set()
        for torrent in torrents:
            result = TitleParser.raw_parser(torrent.name)
            if result is None:
                continue
            identity = (result.title_raw, result.season)
            if identity in seen_identities:
                continue
            result.rss_link = rss.url
            seen_identities.add(identity)
            new_bangumi.append(result)
            logger.info("New bangumi found: %s", result.official_title)
        return new_bangumi

    async def rss_to_data(
        self, rss: RSSItem, engine: RSSEngine, full_parse: bool = True
    ) -> list[Bangumi]:
        """扫描一个源，把未订阅的条目落库为新订阅。

        只处理没匹配上任何现有订阅的条目——已订阅的由 refresh_rss 负责
        投递，这里不重复建条目。
        """
        rss_torrents = await self.get_rss_torrents(rss.url, full_parse)
        bangumi_list = await engine.db.bangumi.search_all()
        unknown = [
            t
            for t in rss_torrents
            if match_bangumi_in_list(t.name, bangumi_list) is None
        ]
        if not unknown:
            logger.debug("No new title has been found.")
            return []
        new_bangumi = await self.torrents_to_data(unknown, rss)
        if new_bangumi:
            await engine.db.bangumi.add_all(new_bangumi)
        return new_bangumi
