"""RSS 拉取 → 标题匹配 → 投递下载器的业务引擎。

参考 RSSEngine 做减法：砍掉通知事件、多引擎快照、按 host 分组
并发与同 host 延迟（#1026）、发布组/分辨率偏好去重、Movie 分支；串行遍历
每个启用源。
"""

import logging
import re
from datetime import datetime, timezone

from module.database import Database
from module.database.bangumi import match_bangumi_in_list
from module.downloader import AddResult, DownloadClient
from module.models import Bangumi, RSSItem, Torrent
from module.network import RequestContent

logger = logging.getLogger(__name__)


class RSSEngine:
    def __init__(self, db: Database):
        self.db = db
        self._filter_cache: dict[str, re.Pattern] = {}

    # ---------------------------------------------------------------- 拉取

    @staticmethod
    async def _get_torrents(rss: RSSItem) -> list[Torrent]:
        async with RequestContent() as req:
            torrents = await req.get_torrents(rss.url)
            # 回填来源，供落库与追溯
            for torrent in torrents:
                torrent.rss_id = rss.id
        return torrents

    async def pull_rss(self, rss_item: RSSItem) -> list[Torrent]:
        """拉取并解析源，剔除 URL 已在库中的条目（去重第二道防线）。"""
        torrents = await self._get_torrents(rss_item)
        return await self.db.torrent.check_new(torrents)

    async def _pull_rss_with_status(
        self, rss_item: RSSItem
    ) -> tuple[list[Torrent], str | None]:
        try:
            return await self.pull_rss(rss_item), None
        except Exception as e:
            logger.warning("Failed to fetch RSS %s: %s", rss_item.name, e)
            return [], str(e)

    # ---------------------------------------------------------------- 匹配

    def _get_filter_pattern(self, filter_str: str) -> re.Pattern:
        """单番排除过滤：`,` 分隔 → `|` 或，命中即排除。"""
        if filter_str not in self._filter_cache:
            raw_pattern = filter_str.replace(",", "|")
            try:
                self._filter_cache[filter_str] = re.compile(raw_pattern, re.IGNORECASE)
            except re.error:
                # 过滤器含非法正则字符（如未闭合的 `[`）时逐词转义做字面量
                # 匹配，而不是让该番全部无法下载
                terms = filter_str.split(",")
                escaped = "|".join(re.escape(t) for t in terms)
                self._filter_cache[filter_str] = re.compile(escaped, re.IGNORECASE)
                logger.warning(
                    "Filter '%s' contains invalid regex, using literal matching",
                    filter_str,
                )
        return self._filter_cache[filter_str]

    def match_torrent(
        self, torrent: Torrent, bangumi_list: list[Bangumi]
    ) -> Bangumi | None:
        """标题匹配 + 单番排除过滤，命中则回填 bangumi_id。

        被过滤掉的种子不关联 bangumi_id：用户明确排除的剧集不能挂在番剧
        名下，否则收集/偏移环节会拿它们当有效集数。
        """
        matched = match_bangumi_in_list(torrent.name, bangumi_list)
        if matched:
            if not matched.filter:
                torrent.bangumi_id = matched.id
                return matched
            pattern = self._get_filter_pattern(matched.filter)
            if not pattern.search(torrent.name):
                torrent.bangumi_id = matched.id
                return matched
        return None

    # ---------------------------------------------------------------- 刷新

    async def refresh_rss(
        self, client: DownloadClient, rss_id: int | None = None
    ) -> None:
        """拉取启用源（或指定源），匹配订阅并投递。

        订阅列表每轮只查一次，全部种子在内存中匹配；每源的连接结果立即
        回写（healthy/error + 时间戳 + 错误信息）。
        """
        if not rss_id:
            rss_items: list[RSSItem] = await self.db.rss.search_active()
        else:
            rss_item = await self.db.rss.search_id(rss_id)
            rss_items = [rss_item] if rss_item else []
        logger.debug("Get %s RSS items", len(rss_items))
        now = datetime.now(timezone.utc).isoformat()
        bangumi_list = await self.db.bangumi.search_all()
        for rss_item in rss_items:
            new_torrents, error = await self._pull_rss_with_status(rss_item)
            await self.db.rss.update_connection_status(
                rss_item.id, "error" if error else "healthy", now, error
            )
            failed_ids: set[int] = set()
            for torrent in new_torrents:
                matched = self.match_torrent(torrent, bangumi_list)
                if not matched:
                    continue
                result = await client.add_torrent(torrent, matched)
                if result is AddResult.FAILED:
                    # 投递失败：不入库（check_new 按 URL 去重，入库就永远不会
                    # 再处理），下轮该种子仍在源里时会重新匹配并重试
                    failed_ids.add(id(torrent))
                    logger.warning(
                        "Failed to add %s, will retry next round", torrent.name
                    )
                else:
                    logger.debug(
                        "Add torrent %s to client (%s)", torrent.name, result.value
                    )
                    torrent.downloaded = True
            to_persist = [t for t in new_torrents if id(t) not in failed_ids]
            await self.db.torrent.add_all(to_persist)
