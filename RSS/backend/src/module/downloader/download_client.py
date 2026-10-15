"""下载器门面：按配置实例化具体客户端并跨操作复用会话。

镜像参考实现的 download_client.py 做减法：裁剪 aria2 分支、客户端引用计数
与延迟关闭、跨层凭据闩锁（闩锁下沉到 QbDownloader 实例）。会话复用的理由
不变：重命名循环每分钟一次操作，每次重登会平白消耗 qB 的登录配额。

配置热重载（AppContext.reload_settings）与测试隔离调用
``_reset_client_cache()`` 丢弃缓存，下次进入时按新配置重建。
"""

import logging

from module.conf import settings
from module.models import Bangumi, Torrent
from module.network import RequestContent

from .base import AddResult, Downloader, RenameOutcome, RenameResult
from .path import gen_save_path

logger = logging.getLogger(__name__)

# 模块级客户端缓存（键取连接相关设置，变更即重建）
_client_cache: tuple[tuple, Downloader] | None = None

# 不支持某操作时每个 (客户端类型, 操作) 只警告一次，避免刷日志
_warned_unsupported: set[tuple[str, str]] = set()


def _settings_key() -> tuple:
    d = settings.downloader
    return (d.type, d.host, d.username, d.password, d.ssl)


def _reset_client_cache() -> None:
    """丢弃缓存的客户端（配置热重载与测试隔离用）。"""
    global _client_cache
    _client_cache = None
    _warned_unsupported.clear()


def _make_client() -> Downloader:
    """按配置实例化具体客户端（qbittorrent | mock）。"""
    downloader_type = settings.downloader.type
    if downloader_type == "qbittorrent":
        from .client.qb_downloader import QbDownloader

        return QbDownloader(
            settings.downloader.host,
            settings.downloader.username,
            settings.downloader.password,
            settings.downloader.ssl,
        )
    if downloader_type == "mock":
        from .client.mock_downloader import MockDownloader

        logger.debug("Using MockDownloader for local development")
        return MockDownloader()
    raise ValueError(f"Unsupported downloader type: {downloader_type}")


async def shutdown() -> None:
    """登出并关闭缓存的客户端（AppContext 停机时调用）。"""
    global _client_cache
    client = _client_cache[1] if _client_cache is not None else None
    _client_cache = None
    if client is not None:
        try:
            await client.close()
        except Exception as e:
            logger.debug("Error closing downloader client: %s", e)


class DownloadClient:
    """统一下载器入口（async 上下文管理器，进入时登录）。"""

    def __init__(self):
        global _client_cache
        key = _settings_key()
        if _client_cache is not None and _client_cache[0] == key:
            self.client = _client_cache[1]
        else:
            self.client = _make_client()
            _client_cache = (key, self.client)

    # ---------------------------------------------------------- 生命周期

    async def __aenter__(self) -> "DownloadClient":
        await self.login()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        # 会话跨操作复用，不在这里登出；生命周期归 shutdown()
        pass

    async def login(self) -> None:
        if not await self.client.login():
            raise ConnectionError("Download client authentication failed")

    @property
    def last_auth_error(self) -> str | None:
        """最近一次认证失败原因（unreachable|credentials|banned）。"""
        return getattr(self.client, "last_auth_error", None)

    def _supports(self, capability: str, op: str) -> bool:
        """具体客户端是否支持该操作；不支持时每个 (类型, 操作) 只警告一次。"""
        if getattr(self.client.capabilities, capability, False):
            return True
        key = (type(self.client).__name__, op)
        if key not in _warned_unsupported:
            _warned_unsupported.add(key)
            logger.warning(
                "%s does not support '%s'; skipping.",
                type(self.client).__name__,
                op,
            )
        return False

    # ---------------------------------------------------------- 业务接口

    async def check(self) -> str | None:
        try:
            return await self.client.check()
        except Exception as e:
            logger.debug("Downloader check failed: %s", e)
            return None

    async def add_torrent(self, torrent: Torrent, bangumi: Bangumi) -> AddResult:
        """投递单个种子，标签 ``ab:{bangumi_id}`` 供重命名时反查偏移量。

        磁力链直接投 URL；否则先抓 .torrent 字节再上传。失败返回 FAILED，
        由调用方决定重试（本轮不落库、下轮自然重试）。
        """
        if not bangumi.save_path:
            bangumi.save_path = gen_save_path(bangumi)
        url = None
        torrent_bytes = None
        if "magnet" in torrent.url:
            url = torrent.url
        else:
            async with RequestContent() as req:
                torrent_bytes = await req.get_content(torrent.url)
            if torrent_bytes is None:
                logger.warning("Failed to fetch torrent file: %s", torrent.url)
                return AddResult.FAILED
        tags = [f"ab:{bangumi.id}"] if bangumi.id else []
        try:
            return await self.client.add_torrent(
                name=torrent.name,
                url=url,
                save_path=bangumi.save_path,
                tags=tags,
                torrent_bytes=torrent_bytes,
            )
        except Exception as e:
            logger.error("Failed to add torrent %s: %s", torrent.name, e)
            return AddResult.FAILED

    async def get_torrent_info(
        self,
        category: str = "Bangumi",
        status_filter: str = "completed",
        tag: str | None = None,
    ) -> list[dict]:
        if not self._supports("can_query", "get_torrent_info"):
            return []
        return await self.client.get_torrent_info(
            category=category, status_filter=status_filter, tag=tag
        )

    async def get_torrent_files(self, torrent_hash: str) -> list[dict]:
        if not self._supports("can_query", "get_torrent_files"):
            return []
        return await self.client.get_torrent_files(torrent_hash)

    async def rename_torrent_file(
        self, torrent_hash: str, old_path: str, new_path: str, verify: bool = True
    ) -> RenameResult:
        if not self._supports("can_rename", "rename_torrent_file"):
            return RenameResult(
                RenameOutcome.RETRYABLE_FAILURE,
                detail=f"{type(self.client).__name__} does not support file rename",
            )
        result = await self.client.rename_torrent_file(
            torrent_hash, old_path, new_path, verify=verify
        )
        if result.succeeded:
            logger.info("%s >> %s", old_path, new_path)
        else:
            logger.debug(
                "Rename %s: %s >> %s", result.outcome.value, old_path, new_path
            )
        return result

    async def add_tag(self, torrent_hash: str, tag: str) -> None:
        if not self._supports("can_manage", "add_tag"):
            return
        await self.client.add_tag(torrent_hash, tag)
        logger.debug("Added tag '%s' to torrent %s", tag, torrent_hash[:8])
