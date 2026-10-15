"""QbDownloader 行为测试：httpx.MockTransport 驱动，不依赖真实 qB 实例。

覆盖参考实现踩过的坑：凭据失败闩锁（防 IP ban）、会话失效单飞重登、
"Fails." 的重复三态判定、renameFile 的 form data 与轮询验证、addTags 的
hashes 管道拼接（#1046）。
"""

import asyncio
import base64
import hashlib
from urllib.parse import parse_qs

import httpx
import pytest

from module.downloader.base import AddResult, RenameOutcome
from module.downloader.client.qb_downloader import QbDownloader

BTIH_HEX = "a" * 40


def make_qb(handler) -> QbDownloader:
    """构造注入 MockTransport 的实例（绕过 _new_client 的真实连接）。"""
    qb = QbDownloader("127.0.0.1:8080", "admin", "adminadmin", ssl=False)
    qb._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return qb


def form_of(request: httpx.Request) -> dict[str, str]:
    """解析 form-urlencoded 请求体。"""
    return {k: v[0] for k, v in parse_qs(request.content.decode()).items()}


@pytest.fixture
def no_sleep(monkeypatch):
    async def _sleep(_seconds):
        return None

    monkeypatch.setattr(asyncio, "sleep", _sleep)


# ------------------------------------------------------------------- 认证


async def test_login_ok():
    def handler(request):
        assert request.url.path == "/api/v2/auth/login"
        assert form_of(request) == {"username": "admin", "password": "adminadmin"}
        return httpx.Response(200, text="Ok.")

    qb = make_qb(handler)
    assert await qb.login() is True
    assert qb.last_auth_error is None


async def test_login_accepts_empty_204():
    qb = make_qb(lambda request: httpx.Response(204))
    assert await qb.login() is True


async def test_login_reuses_session():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(200, text="Ok.")

    qb = make_qb(handler)
    assert await qb.login() is True
    assert await qb.login() is True
    assert calls == ["/api/v2/auth/login"]


async def test_login_wrong_credentials_latches(no_sleep):
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(200, text="Fails.")

    qb = make_qb(handler)
    assert await qb.login() is False
    assert qb.last_auth_error == "credentials"
    # 闩锁后（含后续探测）不再发 login POST，避免累积触发 qB IP ban
    assert await qb.login() is False
    assert calls == ["/api/v2/auth/login"]


async def test_login_401_is_credentials(no_sleep):
    qb = make_qb(lambda request: httpx.Response(401))
    assert await qb.login() is False
    assert qb.last_auth_error == "credentials"


async def test_login_403_is_banned(no_sleep):
    qb = make_qb(lambda request: httpx.Response(403))
    assert await qb.login() is False
    assert qb.last_auth_error == "banned"


async def test_login_unreachable_retries_then_gives_up(no_sleep):
    calls = []

    def handler(request):
        calls.append(request.url.path)
        raise httpx.ConnectError("boom")

    qb = make_qb(handler)
    assert await qb.login(retry=2) is False
    assert qb.last_auth_error == "unreachable"
    assert len(calls) == 2


async def test_request_403_relogins_once(no_sleep):
    login_calls = []
    info_calls = []

    def handler(request):
        path = request.url.path
        if path.endswith("auth/login"):
            login_calls.append(path)
            return httpx.Response(200, text="Ok.")
        if path.endswith("torrents/info"):
            info_calls.append(path)
            if len(info_calls) == 1:
                return httpx.Response(403)
            return httpx.Response(200, json=[])
        raise AssertionError(path)

    qb = make_qb(handler)
    await qb.login()
    assert await qb.get_torrent_info() == []
    assert len(login_calls) == 2  # 初始登录 + 403 后的单飞重登
    assert len(info_calls) == 2


async def test_request_403_relogin_failure_raises(no_sleep):
    login_calls = []
    info_calls = []

    def handler(request):
        path = request.url.path
        if path.endswith("auth/login"):
            login_calls.append(path)
            if len(login_calls) == 1:
                return httpx.Response(200, text="Ok.")
            return httpx.Response(200, text="Fails.")
        if path.endswith("torrents/info"):
            info_calls.append(path)
            return httpx.Response(403)
        raise AssertionError(path)

    qb = make_qb(handler)
    await qb.login()
    with pytest.raises(ConnectionError):
        await qb.get_torrent_info()
    assert len(info_calls) == 1  # 重登失败后不再重试原请求


# ------------------------------------------------------------------- 投递


async def test_add_torrent_ok():
    captured = {}

    def handler(request):
        path = request.url.path
        if path.endswith("auth/login"):
            return httpx.Response(200, text="Ok.")
        if path.endswith("torrents/add"):
            captured.update(form_of(request))
            return httpx.Response(200, text="Ok.")
        raise AssertionError(path)

    qb = make_qb(handler)
    await qb.login()
    result = await qb.add_torrent(
        name="[Group] Anime - 01",
        url=f"magnet:?xt=urn:btih:{BTIH_HEX}",
        save_path="/downloads/Bangumi/Anime (2023)/Season 1",
        tags=["ab:7"],
    )
    assert result is AddResult.ADDED
    assert captured["savepath"] == "/downloads/Bangumi/Anime (2023)/Season 1"
    assert captured["category"] == "Bangumi"
    assert captured["paused"] == "false"
    assert captured["autoTMM"] == "false"
    assert captured["contentLayout"] == "NoSubfolder"
    assert captured["tags"] == "ab:7"
    assert captured["urls"] == f"magnet:?xt=urn:btih:{BTIH_HEX}"


async def test_add_torrent_json_success_count():
    def handler(request):
        if request.url.path.endswith("auth/login"):
            return httpx.Response(200, text="Ok.")
        return httpx.Response(
            200, json={"success_count": 1, "failure_count": 0, "pending_count": 0}
        )

    qb = make_qb(handler)
    await qb.login()
    result = await qb.add_torrent("n", "magnet:?x", "/x", [])
    assert result is AddResult.ADDED


async def test_add_torrent_json_pending_counts_as_added():
    def handler(request):
        if request.url.path.endswith("auth/login"):
            return httpx.Response(200, text="Ok.")
        return httpx.Response(
            202, json={"success_count": 0, "failure_count": 0, "pending_count": 1}
        )

    qb = make_qb(handler)
    await qb.login()
    result = await qb.add_torrent("n", "magnet:?x", "/x", [])
    assert result is AddResult.ADDED


async def test_add_fails_magnet_duplicate():
    magnet = f"magnet:?xt=urn:btih:{BTIH_HEX}&dn=x"
    info_queries = []

    def handler(request):
        path = request.url.path
        if path.endswith("auth/login"):
            return httpx.Response(200, text="Ok.")
        if path.endswith("torrents/add"):
            return httpx.Response(200, text="Fails.")
        if path.endswith("torrents/info"):
            info_queries.append(request.url.params.get("hashes"))
            # qB 回传的 hash 大小写不保证——按小写比对
            return httpx.Response(200, json=[{"hash": BTIH_HEX.upper()}])
        raise AssertionError(path)

    qb = make_qb(handler)
    await qb.login()
    result = await qb.add_torrent("n", magnet, "/x", [])
    assert result is AddResult.DUPLICATE
    assert info_queries == [BTIH_HEX]


async def test_add_fails_base32_magnet_duplicate():
    hex_hash = "ab" * 20
    b32_hash = base64.b32encode(bytes.fromhex(hex_hash)).decode()
    magnet = f"magnet:?xt=urn:btih:{b32_hash}"
    info_queries = []

    def handler(request):
        path = request.url.path
        if path.endswith("auth/login"):
            return httpx.Response(200, text="Ok.")
        if path.endswith("torrents/add"):
            return httpx.Response(200, text="Fails.")
        if path.endswith("torrents/info"):
            info_queries.append(request.url.params.get("hashes"))
            return httpx.Response(200, json=[{"hash": hex_hash}])
        raise AssertionError(path)

    qb = make_qb(handler)
    await qb.login()
    result = await qb.add_torrent("n", magnet, "/x", [])
    assert result is AddResult.DUPLICATE
    # base32 已归一成 hex 再查询
    assert info_queries == [hex_hash]


async def test_add_fails_magnet_not_found_raises():
    def handler(request):
        path = request.url.path
        if path.endswith("auth/login"):
            return httpx.Response(200, text="Ok.")
        if path.endswith("torrents/add"):
            return httpx.Response(200, text="Fails.")
        if path.endswith("torrents/info"):
            return httpx.Response(200, json=[])
        raise AssertionError(path)

    qb = make_qb(handler)
    await qb.login()
    with pytest.raises(ConnectionError):
        await qb.add_torrent("n", f"magnet:?xt=urn:btih:{BTIH_HEX}", "/x", [])


async def test_add_fails_with_bytes_raises():
    def handler(request):
        path = request.url.path
        if path.endswith("auth/login"):
            return httpx.Response(200, text="Ok.")
        if path.endswith("torrents/add"):
            return httpx.Response(200, text="Fails.")
        raise AssertionError(path)  # 字节投递不做重复探测

    qb = make_qb(handler)
    await qb.login()
    with pytest.raises(ConnectionError):
        await qb.add_torrent("n", None, "/x", [], torrent_bytes=b"d8:announce0:e")


async def test_add_409_with_bytes_is_duplicate():
    def handler(request):
        path = request.url.path
        if path.endswith("auth/login"):
            return httpx.Response(200, text="Ok.")
        if path.endswith("torrents/add"):
            return httpx.Response(409)
        raise AssertionError(path)

    qb = make_qb(handler)
    await qb.login()
    result = await qb.add_torrent("n", None, "/x", [], torrent_bytes=b"d8:announce0:e")
    assert result is AddResult.DUPLICATE


async def test_add_415_raises():
    def handler(request):
        path = request.url.path
        if path.endswith("auth/login"):
            return httpx.Response(200, text="Ok.")
        return httpx.Response(415)

    qb = make_qb(handler)
    await qb.login()
    with pytest.raises(ConnectionError):
        await qb.add_torrent("n", None, "/x", [], torrent_bytes=b"garbage")


# --------------------------------------------------------------- 重命名


async def test_rename_409_destination_exists(no_sleep):
    def handler(request):
        if request.url.path.endswith("auth/login"):
            return httpx.Response(200, text="Ok.")
        return httpx.Response(409)

    qb = make_qb(handler)
    await qb.login()
    result = await qb.rename_torrent_file("h" * 40, "old.mkv", "new.mkv")
    assert result.outcome is RenameOutcome.DESTINATION_EXISTS
    assert not result


async def test_rename_500_retryable(no_sleep):
    def handler(request):
        if request.url.path.endswith("auth/login"):
            return httpx.Response(200, text="Ok.")
        return httpx.Response(500)

    qb = make_qb(handler)
    await qb.login()
    result = await qb.rename_torrent_file("h" * 40, "old.mkv", "new.mkv")
    assert result.outcome is RenameOutcome.RETRYABLE_FAILURE


async def test_rename_success_verified(no_sleep):
    forms = []

    def handler(request):
        path = request.url.path
        if path.endswith("auth/login"):
            return httpx.Response(200, text="Ok.")
        if path.endswith("torrents/renameFile"):
            forms.append(form_of(request))
            return httpx.Response(204)
        if path.endswith("torrents/files"):
            return httpx.Response(200, json=[{"name": "new.mkv"}])
        raise AssertionError(path)

    qb = make_qb(handler)
    await qb.login()
    result = await qb.rename_torrent_file("h" * 40, "old.mkv", "new.mkv")
    assert result.outcome is RenameOutcome.RENAMED
    # form data 提交（非 JSON）
    assert forms == [{"hash": "h" * 40, "oldPath": "old.mkv", "newPath": "new.mkv"}]


async def test_rename_target_never_appears_retryable(no_sleep):
    def handler(request):
        path = request.url.path
        if path.endswith("auth/login"):
            return httpx.Response(200, text="Ok.")
        if path.endswith("torrents/renameFile"):
            return httpx.Response(204)
        if path.endswith("torrents/files"):
            return httpx.Response(200, json=[{"name": "old.mkv"}])
        raise AssertionError(path)

    qb = make_qb(handler)
    await qb.login()
    result = await qb.rename_torrent_file("h" * 40, "old.mkv", "new.mkv")
    assert result.outcome is RenameOutcome.RETRYABLE_FAILURE


async def test_rename_verify_false_skips_polling(no_sleep):
    calls = []

    def handler(request):
        path = request.url.path
        calls.append(path)
        if path.endswith("auth/login"):
            return httpx.Response(200, text="Ok.")
        return httpx.Response(204)

    qb = make_qb(handler)
    await qb.login()
    result = await qb.rename_torrent_file("h" * 40, "old.mkv", "new.mkv", verify=False)
    assert result.outcome is RenameOutcome.RENAMED
    assert not any(p.endswith("torrents/files") for p in calls)


# ---------------------------------------------------------------- 标签


async def test_add_tag_pipe_joins_hashes():
    captured = {}

    def handler(request):
        path = request.url.path
        if path.endswith("auth/login"):
            return httpx.Response(200, text="Ok.")
        if path.endswith("torrents/addTags"):
            captured.update(form_of(request))
            return httpx.Response(200)
        raise AssertionError(path)

    qb = make_qb(handler)
    await qb.login()
    await qb.add_tag(["h" * 40, "g" * 40], "ab:renamed")
    # 列表会被 form 编码成重复字段并被 qB 静默忽略（#1046）——必须管道拼接
    assert captured["hashes"] == f"{'h' * 40}|{'g' * 40}"
    assert captured["tags"] == "ab:renamed"
