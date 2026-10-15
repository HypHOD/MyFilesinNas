"""蜜柑计划（mikanani.me）RSS 条目解析。

条目结构：``channel/item`` 下 title / link / enclosure@url。
返回 ``(title, download_url, homepage)`` 元组列表，由 RequestContent
统一构造 Torrent 并应用全局过滤（过滤器只写一份）。
"""

import logging

logger = logging.getLogger(__name__)


def rss_parser(soup) -> list[tuple[str, str, str]]:
    results = []
    for item in soup.findall("./channel/item"):
        try:
            title_el = item.find("title")
            title = title_el.text if title_el is not None else None
            if not title:
                continue
            enclosure = item.find("enclosure")
            if enclosure is not None:
                # 有种子附件：下载地址取 enclosure，详情页取 link
                url = enclosure.attrib.get("url")
                link_el = item.find("link")
                homepage = link_el.text if link_el is not None else ""
            else:
                # 无附件（如聚合页）：link 兼具下载与详情用途
                link_el = item.find("link")
                url = link_el.text if link_el is not None else None
                homepage = ""
            if not url:
                continue
            results.append((title, url, homepage))
        except Exception as e:
            logger.warning("解析 RSS 条目失败: %s", e)
            continue
    return results
