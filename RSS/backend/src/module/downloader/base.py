"""下载器抽象：能力声明、结果枚举与统一接口。

镜像参考实现的 base.py 做减法：Protocol 兄弟接口换成一个 ABC（本工程只有
qbittorrent / mock 两个后端且都实现全量接口），裁剪偏好设置、RSS 规则、
暂停/恢复等本阶段用不到的方法。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import ClassVar


class AddResult(Enum):
    """种子投递结果：新增成功 / 已添加过（重复）/ 投递失败。"""

    ADDED = "added"
    DUPLICATE = "duplicate"
    FAILED = "failed"


class RenameOutcome(str, Enum):
    """单文件重命名的后端无关结果。"""

    RENAMED = "renamed"
    ALREADY_APPLIED = "already_applied"
    DESTINATION_EXISTS = "destination_exists"
    RETRYABLE_FAILURE = "retryable_failure"


@dataclass(frozen=True)
class RenameResult:
    """结构化重命名结果：``bool(result)`` 等价于 ``result.succeeded``。"""

    outcome: RenameOutcome
    detail: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.outcome in {
            RenameOutcome.RENAMED,
            RenameOutcome.ALREADY_APPLIED,
        }

    def __bool__(self) -> bool:
        return self.succeeded


@dataclass(frozen=True)
class DownloaderCapabilities:
    """具体下载端能做什么：

    can_query     -- 查询种子信息 / 文件列表
    can_rename    -- 重命名种子内文件
    can_manage    -- 打标签等管理操作
    can_rss_rules -- qB 原生 RSS 规则（本阶段未使用，保留字段对齐参考）
    """

    can_query: bool
    can_rename: bool
    can_manage: bool
    can_rss_rules: bool


class Downloader(ABC):
    """下载器统一接口；后端差异（qBittorrent / mock）由子类吸收。"""

    capabilities: ClassVar[DownloaderCapabilities]

    @abstractmethod
    async def login(self) -> bool:
        """建立会话；失败返回 False（原因见可选的 last_auth_error）。"""

    @abstractmethod
    async def close(self) -> None:
        """结束会话并释放连接。"""

    @abstractmethod
    async def check(self) -> str | None:
        """连通性探测；可达返回版本串，否则 None。"""

    @abstractmethod
    async def add_torrent(
        self,
        name: str,
        url: str | None,
        save_path: str,
        tags: list[str],
        torrent_bytes: bytes | None = None,
    ) -> AddResult:
        """投递种子：磁力链传 url，.torrent 传字节。"""

    @abstractmethod
    async def get_torrent_info(
        self,
        category: str = "Bangumi",
        status_filter: str = "completed",
        tag: str | None = None,
    ) -> list[dict]:
        """按分类/状态/标签查询种子列表（qB torrents/info 的字段结构）。"""

    @abstractmethod
    async def get_torrent_files(self, torrent_hash: str) -> list[dict]:
        """种子内文件列表（qB torrents/files 的字段结构）。"""

    @abstractmethod
    async def rename_torrent_file(
        self, torrent_hash: str, old_path: str, new_path: str, verify: bool = True
    ) -> RenameResult:
        """重命名种子内的一个文件。"""

    @abstractmethod
    async def add_tag(self, torrent_hash: str, tag: str) -> None:
        """给种子追加标签。"""
