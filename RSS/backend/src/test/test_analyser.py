"""RSSAnalyser 测试：MockTransport 提供 RSS XML → 自动建订阅与批内去重。

非 aggregate 源不参与自动发现是 loops 层的筛选（db.rss.search_aggregate），
在 test_loops 的整链验收里覆盖。
"""

import httpx

from module.database import Database
from module.models import RSSItem
from module.rss import RSSAnalyser, RSSEngine

RSS_URL = "https://mikanani.me/RSS/Bangumi"


def build_rss(items: list[tuple[str, str]]) -> bytes:
    entries = "".join(
        f"<item><title>{title}</title>"
        f'<enclosure url="{url}" type="application/x-bittorrent" length="1"/>'
        f"<link>{url}</link></item>"
        for title, url in items
    )
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        f'<rss version="2.0"><channel><title>Mikan Project - 测试</title>'
        f"{entries}</channel></rss>"
    ).encode()


def install_transport(handler) -> None:
    import module.network.request_url as request_url_module

    request_url_module._transport_override = httpx.MockTransport(handler)


def magnet(hex_char: str) -> str:
    return "magnet:?xt=urn:btih:" + hex_char * 40


async def test_rss_to_data_creates_subscriptions_with_fields(db_engine):
    rss = build_rss(
        [
            ("[LoliHouse] 葬送的芙莉莲 - 05 [1080p].mkv", magnet("a")),
            ("[Sakurato] 无职转生 S02E01 [1080p].mkv", magnet("b")),
            # 合集不是可订阅的正片，解析准入直接拒绝
            ("[LoliHouse] 葬送的芙莉莲 Complete Batch [1080p]", magnet("c")),
        ]
    )
    install_transport(lambda request: httpx.Response(200, content=rss))
    async with Database(engine=db_engine) as db:
        rss_item = await db.rss.add(RSSItem(name="Mikan", url=RSS_URL, aggregate=True))

        created = await RSSAnalyser().rss_to_data(rss_item, RSSEngine(db))

        fulian = next(b for b in created if b.official_title == "葬送的芙莉莲")
        assert fulian.title_raw == "葬送的芙莉莲"
        assert fulian.season == 1
        assert fulian.group_name == "LoliHouse"
        assert fulian.episode_type == "episode"
        assert fulian.rss_link == RSS_URL
        assert fulian.filter == "720,\\d+-\\d+"
        wuzhi = next(b for b in created if b.official_title == "无职转生")
        assert wuzhi.season == 2
        assert wuzhi.group_name == "Sakurato"

        # 合集条目被拒绝，只有两条订阅落库
        assert len(await db.bangumi.search_all()) == 2


async def test_rss_to_data_dedupes_in_batch_and_second_run(db_engine):
    rss = build_rss(
        [
            ("[LoliHouse] 葬送的芙莉莲 - 05 [1080p].mkv", magnet("a")),
            ("[LoliHouse] 葬送的芙莉莲 - 06 [1080p].mkv", magnet("b")),
        ]
    )
    install_transport(lambda request: httpx.Response(200, content=rss))
    async with Database(engine=db_engine) as db:
        rss_item = await db.rss.add(RSSItem(name="Mikan", url=RSS_URL, aggregate=True))
        engine = RSSEngine(db)
        analyser = RSSAnalyser()

        # 批内去重：两集解析出的 (title_raw, season) 相同，只建一条
        first = await analyser.rss_to_data(rss_item, engine)
        assert [b.title_raw for b in first] == ["葬送的芙莉莲"]

        # 二次运行：已订阅的条目被匹配跳过，零新增
        second = await analyser.rss_to_data(rss_item, engine)
        assert second == []
        assert len(await db.bangumi.search_all()) == 1
