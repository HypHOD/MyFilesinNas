"""下载层：门面（DownloadClient）+ 按配置选择的具体下载器（qbittorrent / mock）。"""

from .base import (
    AddResult,
    Downloader,
    DownloaderCapabilities,
    RenameOutcome,
    RenameResult,
)
from .download_client import DownloadClient

__all__ = [
    "AddResult",
    "DownloadClient",
    "Downloader",
    "DownloaderCapabilities",
    "RenameOutcome",
    "RenameResult",
]
