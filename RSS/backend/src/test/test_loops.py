"""整链验收：rss_tick → rename_tick 与 AppContext 接线。

用 _bind_global_database（loops 用无参 ``Database()``）+ mock 下载器 +
本地 mikan fixture 走完「聚合扫描建订阅 → 拉取匹配投递 → 完成后重命名」
全流程；另覆盖：非 aggregate 源不参与自动发现（test_analyser 里注明在
此处覆盖）、启动等待下载器的三种分支、配置热重载重置下载器缓存。
"""

import asyncio

from module.conf import settings
from module.core.context import AppContext
from module.core.loops import rename_tick, rss_tick
from module.database import Database
from module.downloader import DownloadClient
from module.models import RSSItem
from module.rss import RSSAnalyser

RSS_URL = "https://mikanani.me/RSS/Bangumi"


async def test_rss_tick_end_to_end(
    _bind_global_database, mock_downloader_settings, rss_transport
):
    async with Database() as db:
        await db.rss.add(RSSItem(name="Mikan", url=RSS_URL, aggregate=True))

    await rss_tick(RSSAnalyser())

    async with Database() as db:
        subscriptions = {b.official_title for b in await db.bangumi.search_all()}
        assert subscriptions == {"葬送的芙莉莲", "无职转生"}
        (rss,) = await db.rss.search_all()
        assert rss.connection_status == "healthy"
        assert rss.last_checked_at is not None
        assert rss.last_error is None
        # 两条都匹配上了订阅并投递成功 → downloaded 落库、关联订阅与番剧
        torrents = await db.torrent.search_all()
        assert len(torrents) == 2
        assert all(
            t.downloaded and t.bangumi_id is not None and t.rss_id == rss.id
            for t in torrents
        )

    async with DownloadClient() as client:
        assert len(client.client.get_state()["torrents"]) == 2


async def test_rss_tick_does_not_scan_non_aggregate_source(
    _bind_global_database, mock_downloader_settings, rss_transport
):
    async with Database() as db:
        await db.rss.add(RSSItem(name="非聚合源", url=RSS_URL))  # aggregate 默认 False

    await rss_tick(RSSAnalyser())

    async with Database() as db:
        assert await db.bangumi.search_all() == []
    # 非 aggregate 源不经 analyser、没有订阅可匹配 → 不产生投递
    # （孤儿种子会按引擎设计落库，这里只断言行为核心：下载器为空）
    async with DownloadClient() as client:
        assert client.client.get_state()["torrents"] == {}


async def test_rename_tick_renames_completed_torrents(
    _bind_global_database, mock_downloader_settings, rss_transport
):
    async with Database() as db:
        await db.rss.add(RSSItem(name="Mikan", url=RSS_URL, aggregate=True))
    await rss_tick(RSSAnalyser())

    async with DownloadClient() as client:
        for torrent in client.client.get_state()["torrents"].values():
            # mock 投递时不生成文件列表，这里补上并模拟下载完成
            torrent["files"] = [{"name": torrent["name"]}]
            client.client.mark_completed(torrent["hash"])

    await rename_tick()

    async with DownloadClient() as client:
        torrents = client.client.get_state()["torrents"].values()
        names = {f["name"] for t in torrents for f in t["files"]}
        assert names == {"葬送的芙莉莲 S01E05.mkv", "无职转生 S02E01.mkv"}
        assert all("ab:renamed" in t["tags"] for t in torrents)


async def test_app_context_build_rss_task_runs(
    _bind_global_database, mock_downloader_settings, rss_transport
):
    async with Database() as db:
        await db.rss.add(RSSItem(name="Mikan", url=RSS_URL, aggregate=True))

    ctx = AppContext.build(settings)
    rss_task = next(t for t in ctx.scheduler.tasks if t.name == "rss")
    # 直接跑一次 tick 闭包（不真的启动调度循环），验证 build 接线可执行
    await rss_task._run()

    async with Database() as db:
        assert len(await db.bangumi.search_all()) == 2


async def test_wait_for_downloader_passes_immediately_for_mock(
    mock_downloader_settings,
):
    ctx = AppContext.build(settings)
    await asyncio.wait_for(ctx._wait_for_downloader(), timeout=1)


async def test_wait_for_downloader_gives_up_on_credentials(monkeypatch):
    calls = []

    async def fake_check():
        calls.append(1)
        return False, "credentials"

    monkeypatch.setattr(AppContext, "_check_downloader", staticmethod(fake_check))
    ctx = AppContext.build(settings)

    await asyncio.wait_for(ctx._wait_for_downloader(), timeout=1)
    # 凭据错误不重试（继续探测会累积失败登录、加剧 qB IP ban）
    assert len(calls) == 1


async def test_wait_for_downloader_times_out_fail_open(monkeypatch):
    import module.core.context as context_module

    monkeypatch.setattr(context_module, "_DOWNLOADER_RETRY_INTERVAL", 0)
    calls = []

    async def fake_check():
        calls.append(1)
        return False, "unreachable"

    monkeypatch.setattr(AppContext, "_check_downloader", staticmethod(fake_check))
    ctx = AppContext.build(settings)

    await asyncio.wait_for(ctx._wait_for_downloader(), timeout=5)
    # 重试到上限后 fail-open 放行（程序继续运行，下载功能不可用）
    assert len(calls) == context_module._DOWNLOADER_MAX_RETRIES


async def test_reload_settings_resets_downloader_cache():
    original = settings.downloader.type
    settings.downloader.type = "mock"
    settings.save()  # reload 从盘上读，必须先落盘
    try:
        async with DownloadClient() as c1:
            pass
        ctx = AppContext.build(settings)
        await ctx._reload_settings_unlocked()
        async with DownloadClient() as c2:
            assert c2.client is not c1.client
    finally:
        settings.downloader.type = original
        settings.save()
