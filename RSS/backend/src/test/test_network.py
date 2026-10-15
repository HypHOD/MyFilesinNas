"""network 层测试：共享客户端重试/429 退避、mikan 解析与全局过滤。"""

import httpx

import module.network.request_url as request_url_module
from module.conf import settings
from module.network import RequestContent, RequestURL
from module.network.request_url import _retry_after_delay

RETRY_URL = "http://mikan.test/rss"


def install_transport(monkeypatch, handler) -> None:
    """把 MockTransport 注入网络层的共享客户端。"""
    monkeypatch.setattr(
        request_url_module, "_transport_override", httpx.MockTransport(handler)
    )


def patch_sleep(monkeypatch) -> list[float]:
    """拦截 asyncio.sleep，返回记录到的等待时长列表（测试不真实等待）。"""
    delays: list[float] = []

    async def fake_sleep(seconds):
        delays.append(seconds)

    monkeypatch.setattr(request_url_module.asyncio, "sleep", fake_sleep)
    return delays


def make_item(title: str, link: str, enclosure_url: str | None = None) -> str:
    enc = (
        f'<enclosure url="{enclosure_url}" type="application/x-bittorrent" length="1"/>'
        if enclosure_url
        else ""
    )
    return f"<item><title>{title}</title><link>{link}</link>{enc}</item>"


def make_feed(*items: str) -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<rss version="2.0"><channel><title>测试订阅</title>'
        + "".join(items)
        + "</channel></rss>"
    )


def feed_handler(feed: str, *, content: bytes = b""):
    async def handler(request):
        if request.url.path.endswith(".torrent"):
            return httpx.Response(200, content=content)
        return httpx.Response(200, text=feed)

    return handler


# ------------------------------------------------------------------ get_url


async def test_get_url_success(monkeypatch):
    async def handler(request):
        return httpx.Response(200, text="ok")

    install_transport(monkeypatch, handler)
    async with RequestURL() as req:
        resp = await req.get_url(RETRY_URL)
    assert resp is not None
    assert resp.status_code == 200


async def test_get_url_retries_on_request_error(monkeypatch):
    calls = []

    async def handler(request):
        calls.append(request.url)
        if len(calls) < 3:
            raise httpx.ConnectError("boom")
        return httpx.Response(200, text="ok")

    install_transport(monkeypatch, handler)
    delays = patch_sleep(monkeypatch)
    async with RequestURL() as req:
        resp = await req.get_url(RETRY_URL)
    assert resp is not None
    assert len(calls) == 3
    assert delays == [5, 5]


async def test_get_url_gives_up_after_retries(monkeypatch):
    async def handler(request):
        raise httpx.ConnectError("boom")

    install_transport(monkeypatch, handler)
    delays = patch_sleep(monkeypatch)
    async with RequestURL() as req:
        resp = await req.get_url(RETRY_URL)
    assert resp is None
    assert delays == [5, 5]


async def test_get_url_non_429_fails_without_retry(monkeypatch):
    calls = []

    async def handler(request):
        calls.append(request.url)
        return httpx.Response(500)

    install_transport(monkeypatch, handler)
    delays = patch_sleep(monkeypatch)
    async with RequestURL() as req:
        resp = await req.get_url(RETRY_URL)
    assert resp is None
    assert len(calls) == 1
    assert delays == []


async def test_get_url_429_uses_retry_after(monkeypatch):
    calls = []

    async def handler(request):
        calls.append(request.url)
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "2"})
        return httpx.Response(200, text="ok")

    install_transport(monkeypatch, handler)
    delays = patch_sleep(monkeypatch)
    async with RequestURL() as req:
        resp = await req.get_url(RETRY_URL)
    assert resp is not None
    assert delays == [2.0]


def test_retry_after_delay_parsing():
    def response(retry_after: str | None = None):
        headers = {"Retry-After": retry_after} if retry_after is not None else {}
        return httpx.Response(429, headers=headers)

    assert _retry_after_delay(response("2")) == 2.0
    assert _retry_after_delay(response("0.5")) == 0.5
    assert _retry_after_delay(response("120")) == 60.0
    assert _retry_after_delay(response("nan")) == 10.0
    assert _retry_after_delay(response("Wed, 21 Oct 2015 07:28:00 GMT")) == 10.0
    assert _retry_after_delay(response()) == 10.0


# ------------------------------------------------------------------ 条目解析


async def test_get_torrents_prefers_enclosure(monkeypatch):
    feed = make_feed(
        make_item(
            "条目A",
            "https://mikan.test/Home/A",
            "https://mikan.test/Download/A.torrent",
        ),
        make_item("条目B", "https://mikan.test/Home/B"),
    )
    install_transport(monkeypatch, feed_handler(feed))
    async with RequestContent() as req:
        torrents = await req.get_torrents(RETRY_URL)
    assert [t.name for t in torrents] == ["条目A", "条目B"]
    assert torrents[0].url == "https://mikan.test/Download/A.torrent"
    assert torrents[0].homepage == "https://mikan.test/Home/A"
    assert torrents[1].url == "https://mikan.test/Home/B"
    assert torrents[1].homepage == ""


async def test_get_torrents_global_filter_excludes(monkeypatch):
    feed = make_feed(
        make_item("动画 03 [1080p]", "https://mikan.test/a"),
        make_item("动画 03 [720p]", "https://mikan.test/b"),
    )
    install_transport(monkeypatch, feed_handler(feed))
    monkeypatch.setattr(settings.rss_parser, "filter", ["720"])
    async with RequestContent() as req:
        torrents = await req.get_torrents(RETRY_URL)
    assert [t.name for t in torrents] == ["动画 03 [1080p]"]


async def test_get_torrents_empty_filter_keeps_all(monkeypatch):
    feed = make_feed(make_item("动画 03 [720p]", "https://mikan.test/b"))
    install_transport(monkeypatch, feed_handler(feed))
    monkeypatch.setattr(settings.rss_parser, "filter", [])
    async with RequestContent() as req:
        torrents = await req.get_torrents(RETRY_URL)
    assert len(torrents) == 1


async def test_get_torrents_invalid_filter_falls_back_to_literal(monkeypatch):
    feed = make_feed(
        make_item("动画 [aa] 03", "https://mikan.test/a"),
        make_item("动画 03", "https://mikan.test/b"),
    )
    install_transport(monkeypatch, feed_handler(feed))
    monkeypatch.setattr(settings.rss_parser, "filter", ["[aa"])
    async with RequestContent() as req:
        torrents = await req.get_torrents(RETRY_URL)
    assert [t.name for t in torrents] == ["动画 03"]


async def test_get_torrents_bad_xml_returns_empty(monkeypatch):
    async def handler(request):
        return httpx.Response(200, text="<rss><broken>")

    install_transport(monkeypatch, handler)
    async with RequestContent() as req:
        torrents = await req.get_torrents(RETRY_URL)
    assert torrents == []


async def test_get_content_returns_bytes(monkeypatch):
    install_transport(monkeypatch, feed_handler("", content=b"d4:test"))
    async with RequestContent() as req:
        data = await req.get_content("https://mikan.test/Download/A.torrent")
    assert data == b"d4:test"


async def test_get_rss_title(monkeypatch):
    install_transport(monkeypatch, feed_handler(make_feed()))
    async with RequestContent() as req:
        title = await req.get_rss_title(RETRY_URL)
    assert title == "测试订阅"
