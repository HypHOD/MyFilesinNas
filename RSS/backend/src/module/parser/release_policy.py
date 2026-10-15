"""通用解析结果的业务准入策略。

解析回答「资源名里有什么」；本模块回答「当前消费者能否安全使用该结果」。
策略放在 tokenizer 之外，避免下载/数据库的约束渗进解析层。
"""

from __future__ import annotations

from enum import StrEnum

from module.parser.analyser.tokenizer.result import (
    MediaType,
    ParsedRelease,
    ReleaseKind,
)


class PersistenceTarget(StrEnum):
    """当前工程支持的持久化目标。

    参考实现还有 MOVIE（落 Movie 表）；本工程暂无 Movie 表，剧场版
    直接拒绝落库，留此枚举作为后续扩展缝。
    """

    BANGUMI = "bangumi"


_SPECIAL_MEDIA = {MediaType.OVA, MediaType.OAD, MediaType.SPECIAL}
_NON_PERSISTED_MEDIA = {MediaType.PV, MediaType.OPENING, MediaType.ENDING}


def has_release_evidence(release: ParsedRelease) -> bool:
    """标题之外是否还有「发行物形态」的证据（组名/分辨率/编码等）。"""
    return bool(
        release.group
        or release.resolution
        or release.source
        or release.subtitle
        or release.codecs
        or release.audio
        or release.container
    )


def is_weak_title_only(release: ParsedRelease) -> bool:
    """只有标题、没有任何发行物证据的弱解析结果。

    这类结果无法与普通文本区分，落库会生成随机的假订阅，必须拒绝。
    """
    return bool(
        release.primary_title
        and release.media_type is MediaType.UNKNOWN
        and release.release_kind is ReleaseKind.SINGLE
        and release.episode is None
        and not has_release_evidence(release)
    )


def persistence_target(release: ParsedRelease) -> PersistenceTarget | None:
    """返回该发行物当前可落库的目标；不可落库返回 None。

    拒绝面：区间/批次/合集（多集名无法映射为单条订阅）、PV/OP/ED
    （非正片）、剧场版（暂无 Movie 表）、无证据弱标题。
    """
    if (
        not release.primary_title
        or release.release_kind is not ReleaseKind.SINGLE
        or release.media_type in _NON_PERSISTED_MEDIA
    ):
        return None
    if release.media_type is MediaType.MOVIE:
        return None
    if is_weak_title_only(release):
        return None
    return PersistenceTarget.BANGUMI


def bangumi_episode_type(release: ParsedRelease) -> str:
    return "special" if release.media_type in _SPECIAL_MEDIA else "episode"


def normalized_season(release: ParsedRelease, *, default: int = 1) -> int:
    """SP/OVA/OAD 归入 season 0；其余取解析值，缺失按 default。"""
    if release.media_type in _SPECIAL_MEDIA:
        return 0
    return release.season if release.season is not None else default
