"""下载保存路径与下载器文件列表的路径工具。

镜像参考实现的 path.py，裁剪电影（Movie 表后续阶段）与下载器规则名分支。
"""

import logging
import re
from os import PathLike
from pathlib import Path, PureWindowsPath

from module.conf import settings
from module.models import Bangumi, BangumiUpdate

logger = logging.getLogger(__name__)

_MEDIA_SUFFIXES = frozenset({".mp4", ".mkv"})
_SUBTITLE_SUFFIXES = frozenset({".ass", ".srt"})

# Windows/qB 保留字符 + 控制字符：出现在路径片段里会被下载器拆成多级
# 目录或直接丢字（qB 静默截断），必须在拼路径前替换掉 (#721)
_ILLEGAL_PATH_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize_path_fragment(name: str) -> str:
    """把单个路径片段（文件夹名，不含分隔符）里的保留字符替换为空格。

    多余空白折叠为单个空格；Windows 不允许目录名以点或空格结尾，一并去掉。
    幂等：对已合法的名字原样返回。
    """
    cleaned = _ILLEGAL_PATH_CHARS_RE.sub(" ", name)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned.rstrip(". ")


def check_files(files: list[dict]) -> tuple[list[str], list[str]]:
    """下载器文件列表按后缀拆成 (媒体文件, 字幕文件)。"""
    media_list = []
    subtitle_list = []
    for f in files:
        file_name = f["name"]
        suffix = Path(file_name).suffix.lower()
        if suffix in _MEDIA_SUFFIXES:
            media_list.append(file_name)
        elif suffix in _SUBTITLE_SUFFIXES:
            subtitle_list.append(file_name)
    return media_list, subtitle_list


def path_to_bangumi(
    save_path: PathLike[str] | str, torrent_name: str = ""
) -> tuple[str, int]:
    """从 save_path 反推 (番剧目录名, 季号)。

    qBittorrent 跑在 Windows 上时回传的 save_path 是反斜杠分隔，统一用
    PureWindowsPath 切片，保证跨平台解析一致（#1016）；没解出番剧目录名
    时回退种子名。
    """
    save_parts = PureWindowsPath(save_path).parts
    download_parts = PureWindowsPath(settings.downloader.path).parts
    bangumi_name = ""
    season = 1
    for part in save_parts:
        if re.match(r"S\d+|[Ss]eason \d+", part):
            season = int(re.findall(r"\d+", part)[0])
        elif part not in download_parts:
            bangumi_name = part
    if not bangumi_name:
        bangumi_name = torrent_name
    return bangumi_name, season


def file_depth(file_path: PathLike[str] | str) -> int:
    """路径层级数；同样用 PureWindowsPath，兼容 qB 在 Windows 下回传的
    反斜杠路径。"""
    return len(PureWindowsPath(file_path).parts)


def is_ep(file_path: PathLike[str] | str) -> bool:
    """层级 ≤ 2 的文件视为单集文件（更深的目录结构可能是合集/整理过的库）。"""
    return file_depth(file_path) <= 2


def _media_folder(data: Bangumi | BangumiUpdate) -> str:
    title = data.official_title or "Unknown Bangumi"
    folder = sanitize_path_fragment(f"{title} ({data.year})" if data.year else title)
    if folder:
        return folder
    # 标题全由保留字符组成时清洗结果为空——不能让这类条目坍缩到同一个
    # 下载目录里
    return "Unknown Bangumi"


def gen_save_path(data: Bangumi | BangumiUpdate) -> str:
    """生成下载保存路径：``{下载根目录}/{标题 (年份)}/Season {调整后季号}``。

    季号先叠加 season_offset（文件直接落在正确季目录），但不能低于下限
    （普通剧集 1、特别篇 0）——否则 Plex/Jellyfin 会把普通剧集当特别篇；
    越界时回退原季号。
    """
    folder = _media_folder(data)
    episode_type = getattr(data, "episode_type", "episode")
    adjusted_season = data.season + (data.season_offset or 0)
    min_season = 0 if episode_type == "special" else 1
    if adjusted_season < min_season:
        adjusted_season = data.season
        logger.warning(
            "Season offset would result in invalid season for %s, using original season",
            data.official_title,
        )
    return str(Path(settings.downloader.path) / folder / f"Season {adjusted_season}")
