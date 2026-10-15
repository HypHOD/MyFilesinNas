"""release_policy 准入策略 + TitleParser 产物字段测试。"""

import pytest

from module.conf import settings
from module.parser import TitleParser
from module.parser.analyser.tokenizer import MediaType, ParsedRelease, ReleaseKind
from module.parser.release_policy import (
    PersistenceTarget,
    bangumi_episode_type,
    is_weak_title_only,
    normalized_season,
    persistence_target,
)


def make_release(**kwargs) -> ParsedRelease:
    kwargs.setdefault("raw", "test raw")
    kwargs.setdefault("title_en", "Anime Title")
    return ParsedRelease(**kwargs)


# ------------------------------------------------------------ persistence


def test_single_episode_is_persisted():
    release = make_release(media_type=MediaType.EPISODE, episode=3)
    assert persistence_target(release) is PersistenceTarget.BANGUMI


def test_title_only_with_evidence_is_persisted():
    release = make_release(group="LoliHouse", resolution="1080p")
    assert persistence_target(release) is PersistenceTarget.BANGUMI


@pytest.mark.parametrize(
    "kind", [ReleaseKind.RANGE, ReleaseKind.BATCH, ReleaseKind.COLLECTION]
)
def test_multi_episode_kinds_are_rejected(kind):
    release = make_release(release_kind=kind, episode=1, episode_end=12)
    assert persistence_target(release) is None


@pytest.mark.parametrize("media", [MediaType.PV, MediaType.OPENING, MediaType.ENDING])
def test_auxiliary_media_are_rejected(media):
    release = make_release(media_type=media)
    assert persistence_target(release) is None


def test_movie_is_rejected_until_movie_table_exists():
    release = make_release(media_type=MediaType.MOVIE)
    assert persistence_target(release) is None


def test_weak_title_only_is_rejected():
    release = make_release()
    assert is_weak_title_only(release)
    assert persistence_target(release) is None


def test_titleless_release_is_rejected():
    release = ParsedRelease(raw="[1080p]")
    assert persistence_target(release) is None


# ------------------------------------------------------------------ season


def test_normalized_season_defaults_to_one():
    assert normalized_season(make_release()) == 1
    assert normalized_season(make_release(), default=3) == 3


def test_normalized_season_uses_parsed_value():
    assert normalized_season(make_release(season=2)) == 2


@pytest.mark.parametrize("media", [MediaType.OVA, MediaType.OAD, MediaType.SPECIAL])
def test_special_media_normalize_to_season_zero(media):
    assert normalized_season(make_release(media_type=media, season=5)) == 0
    assert bangumi_episode_type(make_release(media_type=media)) == "special"


def test_episode_media_default_type():
    assert bangumi_episode_type(make_release(media_type=MediaType.EPISODE)) == (
        "episode"
    )


# ------------------------------------------------------------- TitleParser


def test_title_parser_builds_bangumi_zh_first():
    bangumi = TitleParser.raw_parser(
        "[LoliHouse] 葬送的芙莉莲 / Sousou no Frieren - 03"
        " [WebRip 1080p HEVC-10bit AAC][简繁内封字幕][MKV]"
    )
    assert bangumi is not None
    assert bangumi.official_title == "葬送的芙莉莲"
    assert bangumi.title_raw == "Sousou no Frieren"
    assert bangumi.season == 1
    assert bangumi.season_raw is None
    assert bangumi.group_name == "LoliHouse"
    assert bangumi.dpi == "1080p"
    assert bangumi.source == "WebRip"
    assert bangumi.subtitle == "简繁内封字幕"
    assert bangumi.episode_offset == 0
    assert bangumi.episode_type == "episode"
    assert bangumi.filter == ",".join(settings.rss_parser.filter)


def test_title_parser_respects_language_preference(monkeypatch):
    monkeypatch.setattr(settings.rss_parser, "language", "en")
    bangumi = TitleParser.raw_parser(
        "[LoliHouse] 葬送的芙莉莲 / Sousou no Frieren - 03 [1080p]"
    )
    assert bangumi is not None
    assert bangumi.official_title == "Sousou no Frieren"


def test_title_parser_season_fields():
    bangumi = TitleParser.raw_parser("[Group] Anime Title S02E05 [1080p]")
    assert bangumi is not None
    assert bangumi.season == 2
    assert bangumi.season_raw == "S02E05"


def test_title_parser_chinese_season():
    bangumi = TitleParser.raw_parser(
        "【幻樱字幕组】【4月新番】"
        "【古见同学有交流障碍症 第二季 Komi-san wa, Komyushou Desu. S02】"
        "【22】【GB_MP4】【1920X1080】"
    )
    assert bangumi is not None
    assert bangumi.season == 2
    assert bangumi.season_raw == "第二季"


def test_title_parser_special_media_builds_special_bangumi():
    bangumi = TitleParser.raw_parser("[Group] Anime Title OVA01 [BDRip 1080p]")
    assert bangumi is not None
    assert bangumi.season == 0
    assert bangumi.episode_type == "special"


def test_title_parser_movie_returns_none():
    assert TitleParser.raw_parser("[Group] 劇場版 呪術廻戦 0 [1080p]") is None


def test_title_parser_range_returns_none():
    assert TitleParser.raw_parser("[Group] Anime [01-12] [1080p]") is None


def test_title_parser_pv_returns_none():
    assert TitleParser.raw_parser("[Group] Anime PV2 [1080p]") is None


def test_title_parser_garbage_returns_none():
    assert TitleParser.raw_parser("[1080p][HEVC][AAC][MKV]") is None
    assert TitleParser.raw_parser("") is None
