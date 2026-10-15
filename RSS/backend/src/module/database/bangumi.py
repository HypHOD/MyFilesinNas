import re
from typing import TYPE_CHECKING

from sqlalchemy import false, select
from sqlalchemy.ext.asyncio import AsyncSession

from module.models import Bangumi, BangumiUpdate

if TYPE_CHECKING:
    from module.parser.analyser.tokenizer.result import ParsedRelease


def _normalize_group_name(group: str | None) -> str:
    """归一化组名：去掉常见分隔符并统一小写。"""
    if not group:
        return ""
    return re.sub(r"[&×_\-]", "", group).lower().strip()


def _groups_are_similar(group1: str | None, group2: str | None) -> bool:
    """两个组名是否可视为同一字幕组。

    覆盖 "LoliHouse" vs "LoliHouse&动漫国字幕组" 这类合作组名。
    """
    if not group1 or not group2:
        return False
    if group1 == group2 or group1 in group2 or group2 in group1:
        return True
    norm1 = _normalize_group_name(group1)
    norm2 = _normalize_group_name(group2)
    return norm1 in norm2 or norm2 in norm1


def _title_patterns(bangumi: Bangumi) -> list[str]:
    """条目可参与匹配的标题模式（参考实现的别名表已裁剪，仅 title_raw）。"""
    return [bangumi.title_raw] if bangumi.title_raw else []


def match_bangumi_in_list(
    torrent_name: str, bangumi_list: list[Bangumi]
) -> Bangumi | None:
    """把种子名匹配到已加载的订阅列表（纯内存，供每轮刷新批量复用）。

    解析结果不是单集正片（区间/合集/PV/OP/ED/弱标题）时直接不匹配；
    命中多个模式时取最长者，获得最高特异性。
    """
    # 惰性 import：database 处于启动期 import 链路靠前的位置，避免绕圈
    from module.parser.analyser.raw_parser import raw_parser
    from module.parser.release_policy import PersistenceTarget, persistence_target

    release = raw_parser(torrent_name)
    if release is None or persistence_target(release) is not PersistenceTarget.BANGUMI:
        return None
    # title_raw 由解析器重组（剔除中间的集数、拼接别名），未必是种子名的
    # 子串（#1103、#1114）；与本种子重组出的标题完全相等也算命中。
    release_title = release.primary_title
    best_match: Bangumi | None = None
    best_rank = (-1, -1, -1)
    for bangumi in bangumi_list:
        if bangumi.deleted or not _release_matches_bangumi(release, bangumi):
            continue
        for pattern in _title_patterns(bangumi):
            if pattern not in torrent_name and pattern != release_title:
                continue
            group_match = int(_groups_are_similar(release.group, bangumi.group_name))
            rank = (len(pattern), group_match, bangumi.season)
            if rank > best_rank:
                best_match = bangumi
                best_rank = rank
    return best_match


def _release_matches_bangumi(release: "ParsedRelease", bangumi: Bangumi) -> bool:
    """发行物与订阅条目的类型/季度是否相容（假阳性缓解）。

    调用方已用 persistence_target 过滤过一次，这里只做相容性判定。
    """
    from module.parser.analyser.tokenizer import MediaType

    if release.is_mixed_collection:
        return False
    if release.media_type in {MediaType.PV, MediaType.OPENING, MediaType.ENDING}:
        return False
    if release.media_type is MediaType.MOVIE:
        expected_type = "movie"
    elif release.media_type in {MediaType.OVA, MediaType.OAD, MediaType.SPECIAL}:
        expected_type = "special"
    else:
        expected_type = "episode"
    if bangumi.episode_type != expected_type:
        return False
    if expected_type == "special":
        return bangumi.season == 0
    return release.season is None or bangumi.season == release.season


class BangumiDatabase:
    """番剧表操作。所有方法自带 commit, 原子级 commit 调用方无需再提交。"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def add(self, data: Bangumi) -> Bangumi:
        self.session.add(data)
        await self.session.commit()
        # 拿到数据库自动生成的其他键
        await self.session.refresh(data)
        return data

    async def add_all(self, datas: list[Bangumi]) -> list[Bangumi]:
        self.session.add_all(datas)
        await self.session.commit()
        for data in datas:
            await self.session.refresh(data)
        return datas

    async def search_all(self) -> list[Bangumi]:
        """未删除的番剧列表。"""
        result = await self.session.execute(
            select(Bangumi).where(Bangumi.deleted == false())
        )
        return list(result.scalars().all())

    async def search_id(self, bangumi_id: int) -> Bangumi | None:
        return await self.session.get(Bangumi, bangumi_id)

    async def update(self, bangumi_id: int, data: BangumiUpdate) -> Bangumi | None:
        """部分更新：只应用载荷中显式提供的字段。"""
        bangumi = await self.search_id(bangumi_id)
        if bangumi is None:
            return None
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(bangumi, key, value)
        self.session.add(bangumi)
        await self.session.commit()
        await self.session.refresh(bangumi)
        return bangumi

    async def disable_rule(self, bangumi_id: int) -> bool:
        """置 deleted=True, 保留数据。"""
        bangumi = await self.search_id(bangumi_id)
        if bangumi is None:
            return False
        bangumi.deleted = True
        self.session.add(bangumi)
        await self.session.commit()
        return True

    async def delete_one(self, bangumi_id: int) -> bool:
        """硬删除"""
        bangumi = await self.search_id(bangumi_id)
        if bangumi is None:
            return False
        await self.session.delete(bangumi)
        await self.session.commit()
        return True
