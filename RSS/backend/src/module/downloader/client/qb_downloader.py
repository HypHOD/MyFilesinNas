"""qBittorrent WebAPI 客户端（本工程使用的子集）。

镜像参考实现，裁剪：aria2 兼容、paused/stopped 双命名探测、.torrent 字节的
bencode infohash 重复检测（只保留磁力链 btih 三态判定）、add 环节的网络重试
（交给上层下轮重试）。保留的关键行为：

- 认证失败（"Fails." / 401）立刻停止重试并落闩锁——qB 默认 5 次失败登录即
  封 WebUI IP；403 视为 IP 已被封禁；
- 会话失效（403）单飞重登后仅重试一次请求，防止并发请求引发登录风暴；
- 重复投递三态：add 被拒后提取磁力链 btih 查 torrents/info，命中才判
  DUPLICATE，确认不存在则按失败抛出——否则损坏种子会被记成"已下载"、
  永远不重试；
- torrents/renameFile 用 form data 提交，成功后指数退避轮询验证新路径；
- torrents/addTags 的 hashes 必须 "|" 拼成单个字段（列表会被 qB 静默
  忽略，#1046）。
"""

import asyncio
import base64
import logging
import re
from typing import ClassVar

import httpx

from module.downloader.base import (
    AddResult,
    Downloader,
    DownloaderCapabilities,
    RenameOutcome,
    RenameResult,
)

logger = logging.getLogger(__name__)

_MAGNET_BTIH_RE = re.compile(r"xt=urn:btih:([0-9A-Fa-f]{40}|[A-Za-z2-7]{32})")


class QbDownloader(Downloader):
    capabilities: ClassVar[DownloaderCapabilities] = DownloaderCapabilities(
        can_query=True,
        can_rename=True,
        can_manage=True,
        can_rss_rules=True,
    )

    def __init__(self, host: str, username: str, password: str, ssl: bool):
        if "://" not in host:
            scheme = "https" if ssl else "http"
            self.host = f"{scheme}://{host}"
        else:
            self.host = host
        self.username = username
        self.password = password
        self.ssl = ssl
        self._client: httpx.AsyncClient | None = None
        self._authed = False
        # 最近一次认证失败原因（unreachable | credentials | banned），
        # 供启动等待循环区分故障类型；成功后清空
        self.last_auth_error: str | None = None
        # 凭据被拒后的闩锁：不再发送 login POST。实例重建（配置热重载时
        # 缓存按键变化）才能解除
        self._credentials_rejected = False
        # 单飞重登：并发请求同时遇到会话失效时只发一次登录
        self._auth_lock = asyncio.Lock()

    def _url(self, endpoint: str) -> str:
        return f"{self.host}/api/v2/{endpoint}"

    def _new_client(self) -> httpx.AsyncClient:
        timeout = httpx.Timeout(connect=5.0, read=10.0, write=10.0, pool=10.0)
        # keepalive_expiry 让空闲连接及时过期，避免复用被 NAS 空闲回收的
        # 死连接；自签名证书在家用/NAS 场景是常态，不校验证书
        limits = httpx.Limits(
            max_keepalive_connections=5,
            max_connections=10,
            keepalive_expiry=30.0,
        )
        return httpx.AsyncClient(timeout=timeout, limits=limits, verify=False)

    # ------------------------------------------------------------ 认证

    async def login(self, retry: int = 3) -> bool:
        if self._authed:
            return True
        return await self._relogin(retry=retry)

    async def _relogin(self, retry: int = 3) -> bool:
        """单飞登录：持锁者先查会话/闩锁，避免并发重复 POST。"""
        if self._credentials_rejected:
            self.last_auth_error = "credentials"
            return False
        async with self._auth_lock:
            if self._authed:
                return True
            if self._credentials_rejected:
                self.last_auth_error = "credentials"
                return False
            return await self._login_attempt(retry)

    async def _login_attempt(self, retry: int = 3) -> bool:
        times = 0
        use_https = self.host.startswith("https://")
        if self._client is None:
            self._client = self._new_client()
        while times < retry:
            try:
                resp = await self._client.post(
                    self._url("auth/login"),
                    data={"username": self.username, "password": self.password},
                )
                # qB < 5.2 回 200 + "Ok."/"Fails."；qB >= 5.2 成功回 204
                # 空响应体。保留 200 的正文本判定，避免代理返回的
                # 200 + HTML 被误判为登录成功
                if (
                    resp.status_code == 200 and resp.text.startswith("Ok")
                ) or resp.status_code == 204:
                    self._authed = True
                    self.last_auth_error = None
                    return True
                if (
                    resp.status_code == 200 and resp.text.startswith("Fails")
                ) or resp.status_code == 401:
                    # 密码错误重试只会触发 qB 的 WebUI IP ban（默认 5 次失败
                    # 即封禁，之后全部 403），立即落闩锁停止重试
                    self.last_auth_error = "credentials"
                    self._credentials_rejected = True
                    logger.error(
                        "qBittorrent rejected the username or password; "
                        "not retrying to avoid a WebUI IP ban"
                    )
                    break
                if resp.status_code == 403:
                    self.last_auth_error = "banned"
                    logger.error(
                        "Login refused by qBittorrent Server "
                        "(IP banned, release it in qBittorrent settings)"
                    )
                    break
                self.last_auth_error = "unreachable"
                logger.error(
                    "Cannot login %s by %s, retry in 5 seconds",
                    self.host,
                    self.username,
                )
                times += 1
                if times < retry:
                    await asyncio.sleep(5)
            except httpx.ConnectError:
                self.last_auth_error = "unreachable"
                if use_https:
                    logger.error(
                        "Cannot connect via HTTPS; if qBittorrent uses plain "
                        "HTTP, disable SSL in download settings"
                    )
                else:
                    logger.error("Cannot connect to qBittorrent Server")
                times += 1
                if times < retry:
                    await asyncio.sleep(10)
            except Exception as e:
                self.last_auth_error = "unreachable"
                logger.error("Unknown error: %s", e)
                break
        return False

    async def _request(self, method: str, endpoint: str, **kwargs) -> httpx.Response:
        """发请求；会话失效（403）时单飞重登一次后仅重试一次。

        qB 服务重启或回收会话后旧 cookie 立即失效，长会话下每个新 tick
        都会撞上；只重试一次是防止失败登录风暴（会被 qB 判 IP ban）。
        """
        assert self._client is not None, "QbDownloader.login() must run first"
        resp = await self._client.request(method, self._url(endpoint), **kwargs)
        if resp.status_code == 403:
            self._authed = False
            if not await self._relogin():
                raise ConnectionError(
                    f"Re-authentication to qBittorrent at {self.host} failed; "
                    "not retrying request to avoid a login storm"
                )
            resp = await self._client.request(method, self._url(endpoint), **kwargs)
        return resp

    async def _get(self, endpoint: str, **kwargs) -> httpx.Response:
        return await self._request("GET", endpoint, **kwargs)

    async def _post(self, endpoint: str, **kwargs) -> httpx.Response:
        return await self._request("POST", endpoint, **kwargs)

    async def close(self) -> None:
        if self._client is not None:
            # 未认证成功（登录失败/从未登录）时没有服务端会话要释放——跳过
            # logout，避免停机/重启时为注定失败的请求等一次超时
            if self._authed:
                try:
                    await self._client.post(self._url("auth/logout"))
                except httpx.HTTPError as e:
                    logger.debug("Logout request failed (non-critical): %s", e)
            await self._client.aclose()
            self._client = None
        self._authed = False

    async def check(self) -> str | None:
        try:
            if not await self.login():
                return None
            resp = await self._get("app/version")
            return resp.text if resp.status_code == 200 else None
        except Exception as e:
            logger.debug("Checker error: %s", e)
            return None

    # ------------------------------------------------------------ 投递

    @staticmethod
    def _parse_add_response_json(resp: httpx.Response) -> dict | None:
        """qB >= 5.2 的 torrents/add 回 JSON 计数；不是该结构（如代理返回
        的 HTML 错误页）返回 None，走通用失败路径。"""
        try:
            data = resp.json()
        except ValueError:
            return None
        if isinstance(data, dict) and "success_count" in data:
            return data
        return None

    async def _url_already_added(self, url: str | None) -> bool:
        """尽力确认 add 被拒是因为任务已存在：从磁力链提取 btih 查 qB。

        提取不到（.torrent URL / 非磁力链）返回 False，按失败处理——
        URL 去重已在上层拦住重复拉取，这里只做兜底。
        """
        if not url:
            return False
        match = _MAGNET_BTIH_RE.search(url)
        if match is None:
            return False
        btih = match.group(1)
        if len(btih) == 32:
            # base32 infohash 归一成 hex，便于和 qB 回传的 hash 比对
            try:
                btih = base64.b32decode(btih.upper()).hex()
            except ValueError:
                return False
        btih = btih.lower()
        try:
            resp = await self._get("torrents/info", params={"hashes": btih})
            found = {t.get("hash", "").lower() for t in resp.json()}
        except (httpx.HTTPError, ValueError, ConnectionError):
            return False
        return btih in found

    async def add_torrent(
        self,
        name: str,
        url: str | None,
        save_path: str,
        tags: list[str],
        torrent_bytes: bytes | None = None,
    ) -> AddResult:
        data = {
            "savepath": save_path,
            "category": "Bangumi",
            "paused": "false",
            "autoTMM": "false",
            "contentLayout": "NoSubfolder",
        }
        if tags:
            data["tags"] = ",".join(tags)
        files = None
        if torrent_bytes is not None:
            files = {
                "torrents": (
                    "torrent.torrent",
                    torrent_bytes,
                    "application/x-bittorrent",
                )
            }
        elif url:
            data["urls"] = url

        resp = await self._post("torrents/add", data=data, files=files)
        if resp.status_code == 200 and resp.text == "Ok.":
            return AddResult.ADDED
        if resp.status_code in (200, 202):
            # qB >= 5.2 回逐种子 JSON 计数；URL 形式是异步下载（202 +
            # pending_count>0），已受理即算成功。计数全 0 说明什么都没发生
            counts = self._parse_add_response_json(resp)
            if counts is not None and (
                counts.get("success_count") or counts.get("pending_count")
            ):
                return AddResult.ADDED
            # "Fails."（qB <= 5.1）覆盖重复、损坏、磁力链无法解析等所有
            # 拒绝，只有 hash 确认任务已存在时才归类为 DUPLICATE
            if await self._url_already_added(url):
                return AddResult.DUPLICATE
            raise ConnectionError(
                f"qBittorrent rejected torrent add "
                f"({resp.status_code} {resp.text!r}) and no matching torrent found"
            )
        if resp.status_code == 409:
            # qB >= 5.2：全部重复/失败且无 pending 时回 409 Conflict。文件
            # 上传是同步解析的，损坏文件走 415，所以文件的 409 即重复；
            # 磁力链尽力用 btih 确认
            if torrent_bytes is not None or await self._url_already_added(url):
                return AddResult.DUPLICATE
            raise ConnectionError(
                "qBittorrent rejected torrent add (409 Conflict) "
                "and no matching torrent found"
            )
        raise ConnectionError(
            f"qBittorrent rejected torrent add: HTTP {resp.status_code}"
        )

    # ------------------------------------------------------------ 查询

    async def get_torrent_info(
        self,
        category: str = "Bangumi",
        status_filter: str = "completed",
        tag: str | None = None,
    ) -> list[dict]:
        params: dict[str, str] = {}
        if status_filter:
            params["filter"] = status_filter
        if category:
            params["category"] = category
        if tag:
            params["tag"] = tag
        resp = await self._get("torrents/info", params=params)
        return resp.json()

    async def get_torrent_files(self, torrent_hash: str) -> list[dict]:
        resp = await self._get("torrents/files", params={"hash": torrent_hash})
        return resp.json()

    # ------------------------------------------------------------ 重命名

    async def rename_torrent_file(
        self, torrent_hash: str, old_path: str, new_path: str, verify: bool = True
    ) -> RenameResult:
        try:
            resp = await self._post(
                "torrents/renameFile",
                data={"hash": torrent_hash, "oldPath": old_path, "newPath": new_path},
            )
            if resp.status_code == 409:
                return RenameResult(
                    RenameOutcome.DESTINATION_EXISTS,
                    detail="qBittorrent rejected rename with HTTP 409",
                )
            # qB >= 5.2 对成功的 renameFile 回 204（空响应体全局改 204）
            if resp.status_code >= 300:
                return RenameResult(
                    RenameOutcome.RETRYABLE_FAILURE,
                    detail=f"qBittorrent rename returned HTTP {resp.status_code}",
                )
            if not verify:
                return RenameResult(RenameOutcome.RENAMED)
            # 200 不代表改完了——qB 在播种等状态下会延迟生效，指数退避
            # （0.1/0.2/0.4s）轮询确认新路径出现
            for attempt in range(3):
                await asyncio.sleep(0.1 * (2**attempt))
                files = await self.get_torrent_files(torrent_hash)
                if any(f.get("name") == new_path for f in files):
                    return RenameResult(RenameOutcome.RENAMED)
            # 新路径始终未出现就不算成功：盲目返回成功会让重命名循环每轮
            # 重复改名
            return RenameResult(
                RenameOutcome.RETRYABLE_FAILURE,
                detail="qBittorrent did not expose the target path after rename",
            )
        except httpx.HTTPError as e:
            logger.warning("Failed to rename file %s: %s", old_path, e)
            return RenameResult(RenameOutcome.RETRYABLE_FAILURE, detail=str(e))

    # ------------------------------------------------------------ 标签

    @staticmethod
    def _normalize_hashes(hashes: str | list[str] | tuple[str, ...]) -> str:
        """qBittorrent 期望一个 "|" 拼接的 hashes 字段；传 Python 列表会被
        form 编码成重复字段并被静默忽略（#1046）。"""
        return "|".join(hashes) if isinstance(hashes, (list, tuple)) else hashes

    async def add_tag(self, torrent_hash: str | list[str], tag: str) -> None:
        await self._post(
            "torrents/addTags",
            data={"hashes": self._normalize_hashes(torrent_hash), "tags": tag},
        )
