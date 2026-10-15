"""共享 HTTP 客户端与 URL 请求工具。

镜像参考实现的 request_url 模块，裁剪掉代理（http/socks5）与连接池失效
换新客户端等分支，保留三个关键行为：

- 模块级共享 ``httpx.AsyncClient``（连接复用，由 AppContext 在配置热重载
  时统一 reset）；
- HTTP 429 限流按 ``Retry-After`` 退避重试（含 NaN / 上限 / 回退防御）；
- ``follow_redirects=True``：蜜柑镜像站与部分 CDN 会 302 到规范域名，
  不跟随重定向会导致 RSS 拉取失败。
"""

import asyncio
import logging
import math

import httpx

logger = logging.getLogger(__name__)

# 模块级共享客户端；RSS 轮询间隔远大于服务端 keep-alive 超时（60-120s），
# keepalive_expiry=60 让空闲连接在过期前主动丢弃，避免复用死连接
_shared_client: httpx.AsyncClient | None = None

# 测试注入口：非空时 get_shared_client() 用该 transport 构造客户端
_transport_override: httpx.AsyncBaseTransport | None = None

_CONNECTION_LIMITS = httpx.Limits(
    max_keepalive_connections=5,
    max_connections=20,
    keepalive_expiry=60.0,
)

# 无 Retry-After（或非数字形式）时的默认等待，以及对服务端值的上限保护
HTTP_429_FALLBACK_DELAY = 10.0
HTTP_429_MAX_RETRY_AFTER = 60.0


def _retry_after_delay(response: httpx.Response) -> float:
    """从 429 响应解析等待秒数；仅接受数字形式的 Retry-After。

    ``float("nan")`` 能通过解析且 min/max 会传播 NaN，导致
    ``asyncio.sleep(nan)`` 永不唤醒，必须显式防御。
    """
    retry_after = response.headers.get("Retry-After")
    if retry_after is not None:
        try:
            value = float(retry_after)
        except ValueError:
            return HTTP_429_FALLBACK_DELAY
        if math.isnan(value):
            return HTTP_429_FALLBACK_DELAY
        return min(max(value, 0.0), HTTP_429_MAX_RETRY_AFTER)
    return HTTP_429_FALLBACK_DELAY


async def get_shared_client() -> httpx.AsyncClient:
    """惰性创建共享客户端，全应用复用同一连接池。"""
    global _shared_client
    if _shared_client is None:
        timeout = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)
        kwargs = {
            "timeout": timeout,
            "limits": _CONNECTION_LIMITS,
            "follow_redirects": True,
        }
        if _transport_override is not None:
            kwargs["transport"] = _transport_override
        _shared_client = httpx.AsyncClient(**kwargs)
    return _shared_client


async def reset_shared_client() -> None:
    """关闭并清除共享客户端，下次请求时自动创建新连接池。

    配置热重载（AppContext.reload_settings）与测试隔离都走这里。
    """
    global _shared_client
    if _shared_client is not None:
        await _shared_client.aclose()
    _shared_client = None


class RequestURL:
    """URL 请求入口：``async with`` 绑定共享客户端后调用 ``get_url``。"""

    # 更完整的 UA，避免被 Cloudflare 拦截
    DEFAULT_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

    def __init__(self):
        self.header = {"User-Agent": self.DEFAULT_UA, "Accept": "application/xml"}
        self._client: httpx.AsyncClient | None = None

    def _get_headers(self, url: str) -> dict:
        """按目标类型选择 Accept：种子文件与 RSS 的期望类型不同。"""
        base_headers = {
            "User-Agent": self.DEFAULT_UA,
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
        }
        if url.endswith(".torrent") or "/download/" in url:
            base_headers["Accept"] = (
                "application/x-bittorrent, application/octet-stream, */*"
            )
        else:
            base_headers["Accept"] = "application/xml, text/xml, */*"
        return base_headers

    async def get_url(self, url: str, retry: int = 3) -> httpx.Response | None:
        """GET 请求；连接错误重试（间隔 5s），429 按 Retry-After 退避。

        失败返回 None（调用方按"拉取失败"处理），不向上抛异常。
        """
        assert self._client is not None, "RequestURL 必须在 async with 块内使用"
        try_time = 0
        headers = self._get_headers(url)
        while True:
            try:
                req = await self._client.get(url=url, headers=headers)
                logger.debug(
                    "Successfully connected to %s. Status: %s", url, req.status_code
                )
                req.raise_for_status()
                return req
            except httpx.HTTPStatusError as e:
                logger.warning("HTTP %s from %s", e.response.status_code, url)
                if e.response.status_code != 429:
                    break
                try_time += 1
                if try_time >= retry:
                    break
                delay = _retry_after_delay(e.response)
                logger.warning(
                    "Rate limited by %s, retrying in %.0fs (%s/%s)",
                    url,
                    delay,
                    try_time,
                    retry,
                )
                await asyncio.sleep(delay)
            except httpx.RequestError as e:
                logger.warning(
                    "Request error for %s: %s. Retry %s/%s",
                    url,
                    type(e).__name__,
                    try_time + 1,
                    retry,
                )
                try_time += 1
                if try_time >= retry:
                    break
                # 复用同一共享客户端重试：其他协程可能仍有请求在途，
                # 关闭连接池会连带杀掉它们的请求
                await asyncio.sleep(5)
            except Exception as e:
                logger.warning("Unexpected error for %s: %s", url, e)
                break
        logger.error("Unable to connect to %s, Please check your network settings", url)
        return None

    async def __aenter__(self) -> "RequestURL":
        self._client = await get_shared_client()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        # 共享客户端的生命周期由 reset_shared_client 统一管理，
        # 这里不释放；也不要置空 self._client，实例可能被并发复用
        pass
