"""MockDownloader 与 DownloadClient 门面测试。

门面的 .torrent 字节抓取走网络层共享客户端，用 _transport_override 注入
MockTransport；磁力链分支不发网络请求。
"""

import hashlib

import httpx
import pytest

from module.conf import settings
from module.downloader import DownloadClient
from module.downloader.base import AddResult
from module.downloader.client.mock_downloader import MockDownloader
from module.models import Bangumi, Torrent

DOWNLOAD_ROOT = "/downloads/Bangumi"


@pytest.fixture(autouse=True)
def _fixed_download_root(monkeypatch):
    monkeypatch.setattr(settings.downloader, "path", DOWNLOAD_ROOT)


def install_transport(handler) -> None:
    """把网络层共享客户端指向 MockTransport。"""
    import module.network.request_url as request_url_module

    request_url_module._transport_override = httpx.MockTransport(handler)


def make_bangumi(**kwargs) -> Bangumi:
    kwargs.setdefault("id", 1)
    kwargs.setdefault("official_title", "葬送的芙莉莲")
    kwargs.setdefault("year", "2023")
    kwargs.setdefault("season", 1)
    return Bangumi(**kwargs)


# ------------------------------------------------------------ MockDownloader


async def test_mock_add_then_complete():
    mock = MockDownloader()
    name = "[LoliHouse] 葬送的芙莉莲 - 05 [1080p].mkv"
    result = await mock.add_torrent(name, url=None, save_path="/x", tags=["ab:1"])
    assert result is AddResult.ADDED
    torrent_hash = hashlib.sha1(name.encode()).hexdigest()
    assert await mock.get_torrent_info() == []  # downloading 不算 completed
    mock.mark_completed(torrent_hash)
    infos = await mock.get_torrent_info()
    assert len(infos) == 1
    assert infos[0]["hash"] == torrent_hash
    assert infos[0]["tags"] == ["ab:1"]


async def test_mock_rename_updates_files_and_tag_idempotent():
    mock = MockDownloader()
    old = "[LoliHouse] 葬送的芙莉莲 - 05 [1080p].mkv"
    torrent_hash = mock.add_mock_torrent(
        "[LoliHouse] 葬送的芙莉莲 - 05 [1080p].mkv", files=[{"name": old}]
    )
    result = await mock.rename_torrent_file(
        torrent_hash, old, "葬送的芙莉莲 S01E05.mkv"
    )
    assert result.succeeded
    assert await mock.get_torrent_files(torrent_hash) == [
        {"name": "葬送的芙莉莲 S01E05.mkv"}
    ]
    await mock.add_tag(torrent_hash, "ab:renamed")
    await mock.add_tag(torrent_hash, "ab:renamed")
    infos = await mock.get_torrent_info(tag="ab:renamed")
    assert infos[0]["tags"] == ["ab:renamed"]


async def test_mock_add_mock_torrent_defaults():
    mock = MockDownloader()
    torrent_hash = mock.add_mock_torrent("Some Torrent")
    infos = await mock.get_torrent_info()
    assert infos[0]["state"] == "completed"
    assert await mock.get_torrent_files(torrent_hash) == [{"name": "Some Torrent.mkv"}]


# ------------------------------------------------------------ 门面


async def test_facade_add_magnet_sets_tags_and_save_path(mock_downloader_settings):
    bangumi = make_bangumi()
    torrent = Torrent(
        name="[LoliHouse] 葬送的芙莉莲 - 05 [1080p].mkv",
        url="magnet:?xt=urn:btih:" + "a" * 40,
    )
    async with DownloadClient() as client:
        result = await client.add_torrent(torrent, bangumi)
    assert result is AddResult.ADDED
    assert bangumi.save_path == f"{DOWNLOAD_ROOT}/葬送的芙莉莲 (2023)/Season 1"
    (entry,) = client.client.get_state()["torrents"].values()
    assert entry["tags"] == ["ab:1"]
    assert entry["save_path"] == bangumi.save_path


async def test_facade_add_torrent_bytes(mock_downloader_settings):
    install_transport(lambda request: httpx.Response(200, content=b"d8:announce0:e"))
    bangumi = make_bangumi()
    torrent = Torrent(
        name="[LoliHouse] 葬送的芙莉莲 - 05 [1080p].mkv",
        url="https://mikanani.me/Download/20240605/abc.torrent",
    )
    async with DownloadClient() as client:
        result = await client.add_torrent(torrent, bangumi)
    assert result is AddResult.ADDED
    assert len(client.client.get_state()["torrents"]) == 1


async def test_facade_add_torrent_fetch_failure_returns_failed(
    mock_downloader_settings,
):
    install_transport(lambda request: httpx.Response(404))
    bangumi = make_bangumi()
    torrent = Torrent(
        name="[LoliHouse] 葬送的芙莉莲 - 05 [1080p].mkv",
        url="https://mikanani.me/Download/20240605/abc.torrent",
    )
    async with DownloadClient() as client:
        result = await client.add_torrent(torrent, bangumi)
    assert result is AddResult.FAILED
    assert client.client.get_state()["torrents"] == {}


async def test_facade_reuses_cached_client(mock_downloader_settings):
    async with DownloadClient() as first:
        pass
    async with DownloadClient() as second:
        pass
    assert first.client is second.client


async def test_facade_rebuilds_on_settings_change(
    mock_downloader_settings, monkeypatch
):
    async with DownloadClient() as first:
        pass
    monkeypatch.setattr(settings.downloader, "host", "another-host:8080")
    async with DownloadClient() as second:
        pass
    assert first.client is not second.client
