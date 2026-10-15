"""RSSEngine 行为测试：MockTransport 提供 RSS XML，MockDownloader 承接投递。

覆盖去重三件套：URL check_new（pull 层）→ ADDED/DUPLICATE 落库 →
FAILED 不落库且下轮重试；以及连接状态回写与单番排除过滤。
"""

import httpx

from module.database import Database
from module.downloader import DownloadClient
from module.downloader.base import AddResult
from module.models import Bangumi, RSSItem, Torrent
from module.network import RequestContent
from module.rss import RSSEngine

RSS_URL = "https://mikanani.me/RSS/Bangumi"
MAGNET_A = "magnet:?xt=urn:btih:" + "a" * 40
MAGNET_B = "magnet:?xt=urn:btih:" + "b" * 40
TORRENT_ITEM = "[LoliHouse] 葬送的芙莉莲 - 05 [1080p].mkv"


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


def rss_handler(items: list[tuple[str, str]]):
    rss = build_rss(items)

    def handler(request):
        return httpx.Response(200, content=rss)

    return handler


async def add_bangumi(db) -> Bangumi:
    return await db.bangumi.add(
        Bangumi(
            official_title="葬送的芙莉莲",
            title_raw="葬送的芙莉莲",
            group_name="LoliHouse",
            season=1,
            filter="",
        )
    )


# ------------------------------------------------------------------- 拉取


async def test_pull_rss_dedupes_existing_urls(db_engine):
    url_a = "https://mikanani.me/Download/20261015/a.torrent"
    url_b = "https://mikanani.me/Download/20261015/b.torrent"
    install_transport(
        rss_handler(
            [("葬送的芙莉莲 - 05 [1080p]", url_a), ("葬送的芙莉莲 - 06 [1080p]", url_b)]
        )
    )
    async with Database(engine=db_engine) as db:
        rss = await db.rss.add(RSSItem(name="Mikan", url=RSS_URL))
        await db.torrent.add(Torrent(name="葬送的芙莉莲 - 05 [1080p]", url=url_a))
        engine = RSSEngine(db)

        new = await engine.pull_rss(rss)

        assert [t.url for t in new] == [url_b]
        assert new[0].rss_id == rss.id


# ------------------------------------------------------------------- 匹配


def test_filter_pattern_falls_back_to_literal_on_invalid_regex(db_engine):
    engine = RSSEngine(db=None)  # _get_filter_pattern 不触库
    pattern = engine._get_filter_pattern("[Unclosed,1080")
    assert pattern.search("name with [Unclosed bracket")
    assert pattern.search("plain 1080p")
    assert not pattern.search("nothing here")
    # 同一个字符串第二次取走缓存
    assert engine._get_filter_pattern("[Unclosed,1080") is pattern


async def test_match_torrent_filter_rejection_keeps_bangumi_id_none(db_engine):
    async with Database(engine=db_engine) as db:
        bangumi = await db.bangumi.add(
            Bangumi(
                official_title="Anime",
                title_raw="Anime",
                group_name="Group",
                season=1,
                filter="720",
            )
        )
        engine = RSSEngine(db)

        rejected = Torrent(name="[Group] Anime - 05 [720p].mkv", url="https://x/1")
        assert engine.match_torrent(rejected, [bangumi]) is None
        # 被排除的种子不挂 bangumi_id，避免污染后续统计
        assert rejected.bangumi_id is None

        matched = Torrent(name="[Group] Anime - 05 [1080p].mkv", url="https://x/2")
        assert engine.match_torrent(matched, [bangumi]) is bangumi
        assert matched.bangumi_id == bangumi.id


# ---------------------------------------------------------------- 刷新闭环


async def test_refresh_rss_adds_and_persists(db_engine, mock_downloader_settings):
    install_transport(rss_handler([(TORRENT_ITEM, MAGNET_A)]))
    async with Database(engine=db_engine) as db:
        rss = await db.rss.add(RSSItem(name="Mikan", url=RSS_URL))
        bangumi = await add_bangumi(db)
        engine = RSSEngine(db)

        async with DownloadClient() as client:
            await engine.refresh_rss(client)
            state = client.client.get_state()

        (persisted,) = await db.torrent.search_all()
        assert persisted.downloaded is True
        assert persisted.bangumi_id == bangumi.id
        assert persisted.rss_id == rss.id
        (entry,) = state["torrents"].values()
        assert entry["tags"] == [f"ab:{bangumi.id}"]

        refreshed = await db.rss.search_id(rss.id)
        assert refreshed.connection_status == "healthy"
        assert refreshed.last_checked_at is not None
        assert refreshed.last_error is None


async def test_refresh_rss_failed_delivery_not_persisted_and_retried(
    db_engine, mock_downloader_settings
):
    torrent_ok = {"value": False}
    torrent_url = "https://mikanani.me/Download/20261015/a.torrent"
    rss = build_rss([(TORRENT_ITEM, torrent_url)])

    def handler(request):
        if "/Download/" in request.url.path:
            if torrent_ok["value"]:
                return httpx.Response(200, content=b"d8:announce0:e")
            return httpx.Response(404)
        return httpx.Response(200, content=rss)

    install_transport(handler)
    async with Database(engine=db_engine) as db:
        await db.rss.add(RSSItem(name="Mikan", url=RSS_URL))
        await add_bangumi(db)
        engine = RSSEngine(db)

        async with DownloadClient() as client:
            await engine.refresh_rss(client)
            # 投递失败：不落库（落库会被 check_new 永久剔除）
            assert await db.torrent.search_all() == []
            assert client.client.get_state()["torrents"] == {}

            torrent_ok["value"] = True
            await engine.refresh_rss(client)
            state = client.client.get_state()

        (persisted,) = await db.torrent.search_all()
        assert persisted.downloaded is True
        assert len(state["torrents"]) == 1


async def test_refresh_rss_duplicate_persisted_once(
    db_engine, mock_downloader_settings, monkeypatch
):
    install_transport(rss_handler([(TORRENT_ITEM, MAGNET_A)]))
    async with Database(engine=db_engine) as db:
        await db.rss.add(RSSItem(name="Mikan", url=RSS_URL))
        await add_bangumi(db)
        engine = RSSEngine(db)

        async with DownloadClient() as client:
            calls = []
            original = client.client.add_torrent

            async def duplicate_first(**kwargs):
                calls.append(kwargs)
                if len(calls) == 1:
                    return AddResult.DUPLICATE
                return await original(**kwargs)

            monkeypatch.setattr(client.client, "add_torrent", duplicate_first)

            await engine.refresh_rss(client)
            (persisted,) = await db.torrent.search_all()
            # 重复投递语义上已成功，落库且标记 downloaded
            assert persisted.downloaded is True

            # 已落库 → 下轮 check_new 按 URL 剔除，不再投递
            await engine.refresh_rss(client)
            assert len(calls) == 1
            assert len(await db.torrent.search_all()) == 1


async def test_refresh_rss_records_error_and_continues(
    db_engine, mock_downloader_settings, monkeypatch
):
    bad_url = "https://bad.example/RSS"
    install_transport(rss_handler([(TORRENT_ITEM, MAGNET_A)]))
    async with Database(engine=db_engine) as db:
        bad = await db.rss.add(RSSItem(name="坏源", url=bad_url))
        good = await db.rss.add(RSSItem(name="Mikan", url=RSS_URL))
        await add_bangumi(db)
        engine = RSSEngine(db)

        original = RequestContent.get_torrents

        async def flaky(self, url, *args, **kwargs):
            if url == bad_url:
                raise ConnectionError("boom")
            return await original(self, url, *args, **kwargs)

        monkeypatch.setattr(RequestContent, "get_torrents", flaky)

        async with DownloadClient() as client:
            await engine.refresh_rss(client)

        bad_row = await db.rss.search_id(bad.id)
        good_row = await db.rss.search_id(good.id)
        assert bad_row.connection_status == "error"
        assert "boom" in bad_row.last_error
        # 坏源不影响后续源继续处理
        assert good_row.connection_status == "healthy"
        assert len(await db.torrent.search_all()) == 1


async def test_refresh_rss_with_specific_id_processes_only_that_source(
    db_engine, mock_downloader_settings
):
    other_url = "https://mikanani.me/RSS/Other"

    def handler(request):
        if request.url.path == "/RSS/Other":
            return httpx.Response(200, content=build_rss([(TORRENT_ITEM, MAGNET_B)]))
        return httpx.Response(200, content=build_rss([(TORRENT_ITEM, MAGNET_A)]))

    install_transport(handler)
    async with Database(engine=db_engine) as db:
        target = await db.rss.add(RSSItem(name="Mikan", url=RSS_URL))
        other = await db.rss.add(RSSItem(name="Other", url=other_url))
        await add_bangumi(db)
        engine = RSSEngine(db)

        async with DownloadClient() as client:
            await engine.refresh_rss(client, rss_id=target.id)
            assert len(client.client.get_state()["torrents"]) == 1

        assert (await db.rss.search_id(target.id)).connection_status == "healthy"
        # 未指定的源本轮完全不接触
        assert (await db.rss.search_id(other.id)).connection_status is None
