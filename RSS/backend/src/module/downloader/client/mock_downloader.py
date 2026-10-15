"""Mock 下载器：不依赖 qBittorrent 的本地演示 / 测试后端。

内存 dict 模拟种子、文件与标签；add 恒成功，永不自动"下载完成"——完成
时机由测试助手 ``mark_completed`` 手动触发，便于整链测试逐步推进。

参考实现里 tags 存在 str / list 混用问题（add_tag 对字符串执行 append 会
抛 AttributeError 且被静默吞掉），本工程统一为 list[str]——重命名幂等标记
``ab:renamed`` 的行为依赖它。
"""

import hashlib
import logging
from typing import Any, ClassVar

from module.downloader.base import (
    AddResult,
    Downloader,
    DownloaderCapabilities,
    RenameOutcome,
    RenameResult,
)

logger = logging.getLogger(__name__)


class MockDownloader(Downloader):
    capabilities: ClassVar[DownloaderCapabilities] = DownloaderCapabilities(
        can_query=True,
        can_rename=True,
        can_manage=True,
        can_rss_rules=True,
    )

    def __init__(self):
        # hash -> {hash, name, save_path, category, state, progress, files, tags}
        self._torrents: dict[str, dict] = {}
        self._authed = False

    async def login(self) -> bool:
        self._authed = True
        logger.debug("Mock auth successful")
        return True

    async def close(self) -> None:
        self._authed = False

    async def check(self) -> str:
        return "mock"

    async def add_torrent(
        self,
        name: str,
        url: str | None,
        save_path: str,
        tags: list[str],
        torrent_bytes: bytes | None = None,
    ) -> AddResult:
        torrent_hash = hashlib.sha1(name.encode()).hexdigest()
        self._torrents[torrent_hash] = {
            "hash": torrent_hash,
            "name": name,
            "save_path": save_path,
            "category": "Bangumi",
            "state": "downloading",
            "progress": 0.0,
            "files": [],
            "tags": list(tags),
        }
        logger.info("Mock add: %s -> %s", name, save_path)
        return AddResult.ADDED

    async def get_torrent_info(
        self,
        category: str = "Bangumi",
        status_filter: str = "completed",
        tag: str | None = None,
    ) -> list[dict]:
        result = []
        for torrent in self._torrents.values():
            if category and torrent["category"] != category:
                continue
            if status_filter and torrent["state"] != status_filter:
                continue
            if tag and tag not in torrent["tags"]:
                continue
            result.append(torrent)
        return result

    async def get_torrent_files(self, torrent_hash: str) -> list[dict]:
        return self._torrents.get(torrent_hash, {}).get("files", [])

    async def rename_torrent_file(
        self, torrent_hash: str, old_path: str, new_path: str, verify: bool = True
    ) -> RenameResult:
        torrent = self._torrents.get(torrent_hash)
        if torrent is not None:
            for f in torrent["files"]:
                if f["name"] == old_path:
                    f["name"] = new_path
        logger.info("Mock rename: %s >> %s", old_path, new_path)
        return RenameResult(RenameOutcome.RENAMED)

    async def add_tag(self, torrent_hash: str, tag: str) -> None:
        torrent = self._torrents.get(torrent_hash)
        if torrent is not None and tag not in torrent["tags"]:
            torrent["tags"].append(tag)
        logger.debug("Mock add_tag: %s -> %s", torrent_hash[:8], tag)

    # ------------------------------------------------------ 测试助手

    def add_mock_torrent(
        self,
        name: str,
        hash: str | None = None,
        category: str = "Bangumi",
        state: str = "completed",
        save_path: str = "/downloads/Bangumi/Mock",
        files: list[dict] | None = None,
    ) -> str:
        """直接塞一个种子（默认已完成），返回 hash。"""
        torrent_hash = hash or hashlib.sha1(name.encode()).hexdigest()
        if files is None:
            files = [{"name": f"{name}.mkv"}]
        self._torrents[torrent_hash] = {
            "hash": torrent_hash,
            "name": name,
            "save_path": save_path,
            "category": category,
            "state": state,
            "progress": 1.0 if state == "completed" else 0.0,
            "files": files,
            "tags": [],
        }
        return torrent_hash

    def mark_completed(self, torrent_hash: str) -> None:
        """把种子置为已完成（模拟下载结束）。"""
        torrent = self._torrents.get(torrent_hash)
        if torrent is not None:
            torrent["state"] = "completed"
            torrent["progress"] = 1.0

    def get_state(self) -> dict[str, Any]:
        """当前内存状态（调试与断言用）。"""
        return {"torrents": self._torrents}
