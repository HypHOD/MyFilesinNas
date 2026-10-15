"""文件名解析：下载器内的文件路径 → EpisodeFile / SubtitleFile。

与参考实现的差异：torrent_parser 函数改为 TorrentParser 静态方法，缓存直接用
functools.lru_cache（参考是 OrderedDict 手写 LRU）；movie 分支砍掉（Movie 表留
待后续阶段）；未知字幕语言由抛 ValidationError 改为记警告返回 None，避免单个
字幕文件打断整轮重命名。
"""

import logging
import re
from functools import lru_cache
from pathlib import Path

from pydantic import ValidationError

from module.models import EpisodeFile, SubtitleFile

logger = logging.getLogger(__name__)

RULES = [
    r"(.*) - (\d{1,4}(?:\.\d{1,2})?(?!\d|p))(?:v\d{1,2})?(?: )?(?:END)?(.*)",
    r"(.*)[\[\ E](\d{1,4}(?:\.\d{1,2})?)(?:v\d{1,2})?(?: )?(?:END)?[\]\ ](.*)",
    r"(.*)\[(?:第)?(\d{1,4}(?:\.\d{1,2})?)[话集話](?:END)?\](.*)",
    r"(.*)第?(\d{1,4}(?:\.\d{1,2})?)[话話集](?:END)?(.*)",
    r"(.*)(?:S\d{2})?EP?(\d{1,4}(?:\.\d{1,2})?)(.*)",
]

COMPILED_RULES = [re.compile(rule, re.I) for rule in RULES]

SUBTITLE_LANG = {
    "zh-tw": ["tc", "cht", "繁", "zh-tw"],
    "zh": ["sc", "chs", "简", "zh"],
}

_GROUP_SPLIT_RE = re.compile(r"[\[\]()【】（）]")


def get_path_basename(torrent_path: str) -> str:
    return Path(torrent_path).name


def get_group(group_and_title: str) -> tuple[str | None, str]:
    """从规则命中的前半段拆出 [字幕组] 与标题；组名后紧跟数字则不算组名。"""
    n = [x for x in _GROUP_SPLIT_RE.split(group_and_title) if x]
    if len(n) > 1:
        if re.match(r"\d+", n[1]):
            return None, group_and_title
        return n[0], n[1]
    return None, n[0]


def get_season_and_title(season_and_title: str) -> tuple[str, int]:
    """从 "Title S02" / "Title Season 2" 摘出季号，默认第 1 季。"""
    title = re.sub(r"([Ss]|Season )\d{1,3}", "", season_and_title).strip()
    match = re.search(r"([Ss]|Season )(\d{1,3})", season_and_title, re.I)
    season = int(match.group(2)) if match else 1
    return title, season


def get_subtitle_lang(subtitle_name: str) -> str | None:
    for key, value in SUBTITLE_LANG.items():
        for v in value:
            if v in subtitle_name.lower():
                return key
    return None


def _parse_episode(raw_episode: str) -> int | float:
    """规则捕获的集数串（"01" / "48.5"）→ int 或 float，半集保留小数。"""
    value = float(raw_episode)
    return int(value) if value.is_integer() else value


def _match_fields(
    torrent_path: str, torrent_name: str | None, season: int | None
) -> tuple[str | None, str, int, int | float] | None:
    """先拿种子名、再退路径 basename，按 RULES 顺序逐条匹配。"""
    media_path = get_path_basename(torrent_path)
    match_names = (
        [torrent_name, media_path] if torrent_name is not None else [media_path]
    )
    for match_name in match_names:
        for compiled_rule in COMPILED_RULES:
            match_obj = compiled_rule.match(match_name)
            if match_obj is None:
                continue
            group, title = get_group(match_obj.group(1))
            # season=0 是 special 的合法取值，但参考实现此处按 falsy 处理，
            # 会转而从标题里重新解析（如 "S00E19"）——保持一致
            if not season:
                title, season = get_season_and_title(title)
            else:
                title, _ = get_season_and_title(title)
            return group, title, season, _parse_episode(match_obj.group(2))
    return None


class TorrentParser:
    """下载器文件名解析；lru_cache 因为重命名循环会反复解析同一路径。"""

    @staticmethod
    @lru_cache(maxsize=512)
    def parse_media_file(
        torrent_path: str, torrent_name: str | None = None, season: int | None = None
    ) -> EpisodeFile | None:
        fields = _match_fields(torrent_path, torrent_name, season)
        if fields is None:
            return None
        group, title, season, episode = fields
        return EpisodeFile(
            media_path=torrent_path,
            group=group,
            title=title,
            season=season,
            episode=episode,
            suffix=Path(torrent_path).suffix,
        )

    @staticmethod
    @lru_cache(maxsize=512)
    def parse_subtitle_file(
        torrent_path: str, torrent_name: str | None = None, season: int | None = None
    ) -> SubtitleFile | None:
        fields = _match_fields(torrent_path, torrent_name, season)
        if fields is None:
            return None
        group, title, season, episode = fields
        try:
            return SubtitleFile(
                media_path=torrent_path,
                group=group,
                title=title,
                season=season,
                episode=episode,
                language=get_subtitle_lang(get_path_basename(torrent_path)),
                suffix=Path(torrent_path).suffix,
            )
        except ValidationError:
            logger.warning(
                "Cannot recognize subtitle language: %s, skipping.", torrent_path
            )
            return None
