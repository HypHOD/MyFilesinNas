"""RSS XML / 种子文件内容抓取。

镜像参考实现的 request_contents 模块，裁剪掉 JSON / HTML / 连通性探测等
本阶段用不到的接口，保留：XML 解析、条目抓取（含全局过滤）、正文字节、
RSS 标题。
"""

import logging
import re
import xml.etree.ElementTree

from module.conf import settings
from module.models import Torrent

from .request_url import RequestURL
from .site import rss_parser

logger = logging.getLogger(__name__)


class RequestContent(RequestURL):
    async def get_torrents(
        self,
        url: str,
        _filter: str | None = None,
        limit: int | None = None,
        retry: int = 3,
    ) -> list[Torrent]:
        """拉取并解析 RSS 条目，应用全局排除过滤。

        过滤语义是「排除」：命中正则的条目被丢弃。空过滤器必须短路——
        ``re.search("", x)`` 恒真，否则会把所有条目排除光。
        """
        soup = await self.get_xml(url, retry)
        if soup is None:
            logger.warning("Failed to get torrents: %s", url)
            return []
        parsed_items = rss_parser(soup)
        torrents: list[Torrent] = []
        if _filter is None:
            _filter = "|".join(settings.rss_parser.filter)
        pattern = self._compile_exclusion(_filter)
        for title, torrent_url, homepage in parsed_items:
            if pattern is None or pattern.search(title) is None:
                torrents.append(Torrent(name=title, url=torrent_url, homepage=homepage))
            if isinstance(limit, int) and len(torrents) >= limit:
                break
        return torrents

    @staticmethod
    def _compile_exclusion(filter_str: str) -> re.Pattern | None:
        """编译排除过滤正则；空串返回 None（不过滤）。

        全局过滤器由用户配置，可能包含非法正则字符（如未闭合的 ``[``），
        此时逐词转义做字面量匹配，而不是让整条源拉取失败。
        """
        if not filter_str:
            return None
        try:
            return re.compile(filter_str)
        except re.error:
            escaped = "|".join(re.escape(t) for t in filter_str.split("|"))
            logger.warning("全局过滤器 '%s' 含非法正则，回退为字面量匹配", filter_str)
            return re.compile(escaped)

    async def get_xml(
        self, url: str, retry: int = 3
    ) -> xml.etree.ElementTree.Element | None:
        req = await self.get_url(url, retry)
        if req is None:
            return None
        try:
            return xml.etree.ElementTree.fromstring(req.text)
        except xml.etree.ElementTree.ParseError as e:
            logger.warning("Failed to parse XML from %s: %s", url, e)
            return None

    async def get_content(self, url: str) -> bytes | None:
        req = await self.get_url(url)
        if req is None:
            logger.warning("Failed to get content from %s", url)
            return None
        return req.content

    async def get_rss_title(self, url: str) -> str | None:
        soup = await self.get_xml(url)
        if soup is not None:
            title_el = soup.find("./channel/title")
            if title_el is not None:
                return title_el.text
        return None
