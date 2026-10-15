"""下载器内文件重命名：`{title} S{season}E{episode}` 规范命名。

镜像参考实现的 Renamer 做减法：砍掉 rename_operation/revision saga、Movie
分支、通知事件、失败冷却、advance/normal 方法（本工程只用 pn/subtitle_pn）
与合集完成后的分类迁移；只剩「查已完成种子 → 逐文件改名 → 打
``ab:renamed`` 幂等标记」这一条主路径。

几个必须保留的语义（参考实现踩坑记录）：
- 重命名走 qB API，不碰本地文件系统——媒体库目录就是投递时定的 savepath；
- ``ab:renamed`` 是终态标记：已带标记的种子直接跳过，打标失败吞异常下轮
  补打（此时文件已是目标名，改名调用会被自愈逻辑跳过，仍会走打标）；
- 集数偏移三保护：EP0 不偏移（#977）、偏移后非正回退原值、半集 .5 保留
  （#667）；季号只来自季目录名，不二次叠加 offset。
"""

import logging

from module.conf import settings
from module.database import Database
from module.database.bangumi import match_bangumi_in_list
from module.downloader import DownloadClient
from module.downloader.path import check_files, is_ep, path_to_bangumi
from module.models import Bangumi, EpisodeFile, SubtitleFile
from module.parser.analyser.torrent_parser import TorrentParser

logger = logging.getLogger(__name__)

_RENAMED_TAG = "ab:renamed"


class Renamer:
    def __init__(self, client: DownloadClient, db: Database):
        self.client = client
        self.db = db

    # ------------------------------------------------------------ 路径生成

    @staticmethod
    def _adjust_episode(original: int | float, episode_offset: int) -> int | float:
        if original == 0 and episode_offset != 0:
            # EP0 是特别篇/OVA，任何偏移都会把它顶成正片集数 (#977)
            return 0
        adjusted = original + episode_offset
        # 偏移后非正（如 EP5 + offset -10）几乎总是配置错误，回退原集数
        if adjusted < 0 or (adjusted == 0 and original > 0):
            logger.warning(
                "Episode offset %s would make episode %s non-positive, "
                "ignoring offset",
                episode_offset,
                original,
            )
            return original
        return adjusted

    @staticmethod
    def _format_episode(episode: int | float) -> str:
        # 总集篇等半集（12.5）保留小数，否则会覆盖同季的整数集 (#667)
        if isinstance(episode, float) and episode.is_integer():
            episode = int(episode)
        return f"0{episode}" if episode < 10 else str(episode)

    @staticmethod
    def gen_path(
        file_info: EpisodeFile | SubtitleFile,
        bangumi_name: str,
        method: str,
        episode_offset: int = 0,
    ) -> str:
        """按重命名方式生成目标文件名。

        ``bangumi_name`` 保留在签名里对齐参考实现（仅 advance 方式使用，
        本工程未移植）；季号直接取 ``file_info.season``——它来自季目录名，
        已经包含 season_offset，不能在这里再叠加一次。
        """
        season_num = file_info.season
        season = f"0{season_num}" if season_num < 10 else season_num
        episode = Renamer._format_episode(
            Renamer._adjust_episode(file_info.episode, episode_offset)
        )
        if method in ("none", "subtitle_none"):
            return file_info.media_path
        title = file_info.title
        if method == "pn":
            return f"{title} S{season}E{episode}{file_info.suffix}"
        if method == "normal":
            logger.warning("Normal rename method is deprecated.")
            return file_info.media_path
        if method == "subtitle_pn":
            assert isinstance(
                file_info, SubtitleFile
            ), "subtitle_pn requires a SubtitleFile"
            return f"{title} S{season}E{episode}.{file_info.language}{file_info.suffix}"
        logger.error("Unknown rename method: %s", method)
        return file_info.media_path

    # ------------------------------------------------------------ 标签工具

    @staticmethod
    def _tag_list(tags: str | list[str] | None) -> list[str]:
        """统一标签形态：qB 回传逗号分隔字符串，mock 直接给 list[str]。"""
        if not tags:
            return []
        if isinstance(tags, str):
            return [tag.strip() for tag in tags.split(",")]
        return list(tags)

    def _parse_bangumi_id_from_tags(self, tags: str | list[str] | None) -> int | None:
        """从 ``ab:{id}`` 标签中取番剧 id；一对多订阅下这是最准的反查。"""
        for tag in self._tag_list(tags):
            if tag.startswith("ab:"):
                try:
                    return int(tag[3:])
                except ValueError:
                    pass
        return None

    def _has_tag(self, tags: str | list[str] | None, expected: str) -> bool:
        return expected in self._tag_list(tags)

    async def _mark_renamed(
        self, _hash: str, existing_tags: str | list[str] | None
    ) -> None:
        """给处理完成的种子打 ``ab:renamed`` 标签；已带标签时不调 API。

        打标失败绝不能影响重命名主流程——吞掉异常，下一轮会自动补打。
        """
        if self._has_tag(existing_tags, _RENAMED_TAG):
            return
        try:
            await self.client.add_tag(_hash, _RENAMED_TAG)
        except Exception as e:
            logger.warning("Failed to tag %s as renamed: %s", _hash[:8], e)

    # ------------------------------------------------------------ 偏移反查

    async def _lookup_offsets(self, info: dict, bangumi_list: list[Bangumi]) -> int:
        """为种子反查番剧的集数偏移量；查不到返回 0。

        顺序（可靠性从高到低）：
        1. 种子标签 ``ab:{id}``（一对多订阅下不会串号）；
        2. Torrent 表的 qb_hash 记录 → bangumi_id（新投递种子的直达链路）；
        3. 种子名匹配订阅列表。
        """
        bangumi_id = self._parse_bangumi_id_from_tags(info.get("tags"))
        if bangumi_id:
            bangumi = await self.db.bangumi.search_id(bangumi_id)
            if bangumi and not bangumi.deleted:
                return bangumi.episode_offset
        record = await self.db.torrent.search_by_qb_hash(info["hash"])
        if record and record.bangumi_id:
            bangumi = await self.db.bangumi.search_id(record.bangumi_id)
            if bangumi and not bangumi.deleted:
                return bangumi.episode_offset
        bangumi = match_bangumi_in_list(info.get("name", ""), bangumi_list)
        if bangumi:
            return bangumi.episode_offset
        logger.info(
            "No bangumi match for torrent %s, using offset 0",
            info.get("name", "")[:60],
        )
        return 0

    # ------------------------------------------------------------ 重命名

    async def rename_file(
        self,
        torrent_name: str,
        media_path: str,
        bangumi_name: str,
        method: str,
        season: int,
        _hash: str,
        episode_offset: int = 0,
    ) -> bool:
        """重命名单个媒体文件；返回是否处理成功（含"已是目标名"）。"""
        ep = TorrentParser.parse_media_file(
            torrent_path=media_path, torrent_name=torrent_name, season=season
        )
        if not ep:
            logger.warning("Cannot parse file name: %s, skipping.", media_path)
            return False
        new_path = self.gen_path(ep, bangumi_name, method, episode_offset)
        if new_path == media_path:
            # 已是目标名（如上一轮改名成功但打标失败）——自愈，直接视为完成
            return True
        result = await self.client.rename_torrent_file(_hash, media_path, new_path)
        if not result.succeeded:
            logger.warning("%s rename failed: %s", media_path, result.outcome.value)
        return result.succeeded

    async def rename_collection(
        self,
        media_list: list[str],
        bangumi_name: str,
        season: int,
        method: str,
        _hash: str,
        episode_offset: int = 0,
    ) -> bool:
        """重命名合集内的单集文件；任一失败即整体视为未完成、不打标。

        解析失败的文件不会被重命名——不能算处理完成，否则会带着残缺的文件
        集打上 ``ab:renamed`` 而永远不会重试。
        """
        all_renamed = True
        for media_path in media_list:
            if not is_ep(media_path):
                continue
            ep = TorrentParser.parse_media_file(torrent_path=media_path, season=season)
            if not ep:
                all_renamed = False
                logger.warning("Cannot parse file name: %s, skipping.", media_path)
                continue
            new_path = self.gen_path(ep, bangumi_name, method, episode_offset)
            if new_path == media_path:
                continue
            result = await self.client.rename_torrent_file(_hash, media_path, new_path)
            if not result.succeeded:
                all_renamed = False
                logger.warning("%s rename failed: %s", media_path, result.outcome.value)
        return all_renamed

    async def rename_subtitles(
        self,
        subtitle_list: list[str],
        torrent_name: str,
        bangumi_name: str,
        season: int,
        method: str,
        _hash: str,
        episode_offset: int = 0,
    ) -> None:
        """重命名字幕文件；失败仅告警，不影响主流程的完成判定。"""
        method = "subtitle_" + method
        for subtitle_path in subtitle_list:
            sub = TorrentParser.parse_subtitle_file(
                torrent_path=subtitle_path, torrent_name=torrent_name, season=season
            )
            if not sub:
                continue
            new_path = self.gen_path(sub, bangumi_name, method, episode_offset)
            if new_path == subtitle_path:
                continue
            # 字幕跳过改名后的轮询验证，减少延迟（参考实现同）
            result = await self.client.rename_torrent_file(
                _hash, subtitle_path, new_path, verify=False
            )
            if not result.succeeded:
                logger.warning("%s rename failed", subtitle_path)

    # ------------------------------------------------------------ 主流程

    @staticmethod
    def print_result(torrent_count: int, rename_count: int) -> None:
        if rename_count != 0:
            logger.info(
                "Finished checking %s files' name, renamed %s files.",
                torrent_count,
                rename_count,
            )
        logger.debug("Checked %s files", torrent_count)

    async def rename(self) -> None:
        """一轮重命名：查已完成种子 → 跳过 ab:renamed → 逐种子改名打标。"""
        logger.debug("Start rename process.")
        rename_method = settings.bangumi_manage.rename_method
        torrents_info = [
            info
            for info in await self.client.get_torrent_info()
            if not self._has_tag(info.get("tags"), _RENAMED_TAG)
        ]
        if not torrents_info:
            logger.debug("Rename process finished: no pending torrents")
            return
        # 订阅列表每轮只查一次，名称反查在内存中完成
        bangumi_list = await self.db.bangumi.search_all()
        checked_count = 0
        renamed_count = 0
        for info in torrents_info:
            torrent_hash = info["hash"]
            torrent_name = info["name"]
            files = await self.client.get_torrent_files(torrent_hash)
            media_list, subtitle_list = check_files(files)
            if not media_list:
                logger.warning("%s has no media file", torrent_name)
                continue
            checked_count += 1
            bangumi_name, season = path_to_bangumi(
                info.get("save_path", ""), torrent_name
            )
            episode_offset = await self._lookup_offsets(info, bangumi_list)
            if len(media_list) == 1:
                renamed = await self.rename_file(
                    torrent_name=torrent_name,
                    media_path=media_list[0],
                    bangumi_name=bangumi_name,
                    method=rename_method,
                    season=season,
                    _hash=torrent_hash,
                    episode_offset=episode_offset,
                )
            else:
                logger.info("Start rename collection: %s", torrent_name)
                renamed = await self.rename_collection(
                    media_list=media_list,
                    bangumi_name=bangumi_name,
                    season=season,
                    method=rename_method,
                    _hash=torrent_hash,
                    episode_offset=episode_offset,
                )
            if not renamed:
                continue
            renamed_count += 1
            if subtitle_list:
                await self.rename_subtitles(
                    subtitle_list=subtitle_list,
                    torrent_name=torrent_name,
                    bangumi_name=bangumi_name,
                    season=season,
                    method=rename_method,
                    _hash=torrent_hash,
                    episode_offset=episode_offset,
                )
            if rename_method not in ("none", "normal"):
                await self._mark_renamed(torrent_hash, info.get("tags"))
        self.print_result(checked_count, renamed_count)
