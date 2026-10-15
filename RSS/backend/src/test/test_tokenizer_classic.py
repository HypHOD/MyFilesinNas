"""tokenizer 金样本回归测试：证据驱动解析器的行为快照。

样本取自真实番剧资源名（mikan / dmhy 常见样式），覆盖三语标题拆分、
SxxExx、季度词、区间/合集、OVA/SP、PV/OP/ED、歧义标题（Movie/PV 混入
普通标题）与负样本。断言只比较通用字段快照，忽略 evidence 内部轨迹。
"""

from dataclasses import fields

import pytest

from module.parser.analyser.tokenizer import parse_release_title
from module.parser.analyser.tokenizer.normalization import normalize

_DEFAULTS = {
    "title_en": None,
    "title_zh": None,
    "title_jp": None,
    "group": None,
    "season": None,
    "season_raw": None,
    "episode": None,
    "episode_end": None,
    "episode_title": None,
    "media_type": "unknown",
    "release_kind": "single",
    "resolution": None,
    "source": None,
    "subtitle": None,
    "codecs": [],
    "audio": [],
    "container": None,
    "version": None,
    "year": None,
    "tags": [],
}


def _snapshot(parsed) -> dict:
    snapshot = {}
    for name in _DEFAULTS:
        value = getattr(parsed, name)
        if isinstance(value, tuple):
            value = list(value)
        elif hasattr(value, "value"):
            value = value.value
        snapshot[name] = value
    return snapshot


_CASES = [
    pytest.param(
        "[LoliHouse] 葬送的芙莉莲 / Sousou no Frieren - 03 "
        "[WebRip 1080p HEVC-10bit AAC][简繁内封字幕][MKV]",
        {
            "title_en": "Sousou no Frieren",
            "title_zh": "葬送的芙莉莲",
            "group": "LoliHouse",
            "episode": 3,
            "media_type": "episode",
            "resolution": "1080p",
            "source": "WebRip",
            "subtitle": "简繁内封字幕",
            "codecs": ["HEVC-10bit"],
            "audio": ["AAC"],
            "container": "MKV",
        },
        id="三语标题拆分_简繁内封字幕",
    ),
    pytest.param(
        "[喵萌奶茶屋&LoliHouse] 鹿乃子乃子乃子虎视眈眈 / "
        "Shikanoko Nokonoko Koshitantan\n- 01 [WebRip 1080p HEVC-10bit AAC]",
        {
            "title_en": "Shikanoko Nokonoko Koshitantan",
            "title_zh": "鹿乃子乃子乃子虎视眈眈",
            "group": "喵萌奶茶屋&LoliHouse",
            "episode": 1,
            "media_type": "episode",
            "resolution": "1080p",
            "source": "WebRip",
            "codecs": ["HEVC-10bit"],
            "audio": ["AAC"],
        },
        id="mikan多行标题与联合字幕组",
    ),
    pytest.param(
        "[Group] Anime Title S02E05 [WEB-DL 1080p]",
        {
            "title_en": "Anime Title",
            "group": "Group",
            "season": 2,
            "season_raw": "S02E05",
            "episode": 5,
            "media_type": "episode",
            "resolution": "1080p",
            "source": "WEB-DL",
        },
        id="SxxExx与season_raw",
    ),
    pytest.param(
        "[Group] Anime Title Season 2 - 01 [1080p]",
        {
            "title_en": "Anime Title",
            "group": "Group",
            "season": 2,
            "season_raw": "Season 2",
            "episode": 1,
            "media_type": "episode",
            "resolution": "1080p",
        },
        id="Season词式季度",
    ),
    pytest.param(
        "[Group] Anime Title Season 2 Episode 08 [1080p]",
        {
            "title_en": "Anime Title",
            "group": "Group",
            "season": 2,
            "season_raw": "Season 2 Episode 08",
            "episode": 8,
            "media_type": "episode",
            "resolution": "1080p",
        },
        id="Season与Episode词式组合",
    ),
    pytest.param(
        "[EMBER] Frieren - 12.5 [BDRip 1080p AVC 8bit Dual Audio MKV]",
        {
            "title_en": "Frieren",
            "group": "EMBER",
            "episode": 12.5,
            "media_type": "episode",
            "resolution": "1080p",
            "source": "BDRip",
            "codecs": ["AVC", "8bit"],
            "audio": ["Dual Audio"],
            "container": "MKV",
        },
        id="小数集数12.5",
    ),
    pytest.param(
        "[Group] Anime Title - 12v2 [1080p]",
        {
            "title_en": "Anime Title",
            "group": "Group",
            "episode": 12,
            "media_type": "episode",
            "resolution": "1080p",
            "version": 2,
        },
        id="v2版本号",
    ),
    pytest.param(
        "[Group] Anime Title [01-12] [BDRip 1080p]",
        {
            "title_en": "Anime Title",
            "group": "Group",
            "episode": 1,
            "episode_end": 12,
            "media_type": "episode",
            "release_kind": "range",
            "resolution": "1080p",
            "source": "BDRip",
        },
        id="裸区间01-12",
    ),
    pytest.param(
        "[Group] Anime Title [E01-E12] [BDRip 1080p]",
        {
            "title_en": "Anime Title",
            "group": "Group",
            "episode": 1,
            "episode_end": 12,
            "media_type": "episode",
            "release_kind": "range",
            "resolution": "1080p",
            "source": "BDRip",
        },
        id="E前缀区间",
    ),
    pytest.param(
        "[Group] 迷宫饭 全24话 [1080p]",
        {
            "title_zh": "迷宫饭",
            "group": "Group",
            "episode": 1,
            "episode_end": 24,
            "media_type": "episode",
            "release_kind": "collection",
            "resolution": "1080p",
        },
        id="全N话合集带集数区间",
    ),
    pytest.param(
        "[VCB-Studio] Violet Evergarden Complete Batch [BDRip 1080p]",
        {
            "title_en": "Violet Evergarden",
            "group": "VCB-Studio",
            "media_type": "episode",
            "release_kind": "batch",
            "resolution": "1080p",
            "source": "BDRip",
        },
        id="CompleteBatch合集",
    ),
    pytest.param(
        "[Group] 葬送的芙莉莲合集 [BDRip 1080p]",
        {
            "title_zh": "葬送的芙莉莲",
            "group": "Group",
            "media_type": "episode",
            "release_kind": "collection",
            "resolution": "1080p",
            "source": "BDRip",
        },
        id="中文合集",
    ),
    pytest.param(
        "[Group] Anime Title OVA01 [BDRip 1080p]",
        {
            "title_en": "Anime Title",
            "group": "Group",
            "episode": 1,
            "media_type": "ova",
            "resolution": "1080p",
            "source": "BDRip",
        },
        id="OVA带编号",
    ),
    pytest.param(
        "[Group] Anime Title OAD 02 [BDRip 1080p]",
        {
            "title_en": "Anime Title",
            "group": "Group",
            "episode": 2,
            "media_type": "oad",
            "resolution": "1080p",
            "source": "BDRip",
        },
        id="OAD带编号",
    ),
    pytest.param(
        "[Group] Anime Title SP03 [BDRip 1080p]",
        {
            "title_en": "Anime Title",
            "group": "Group",
            "episode": 3,
            "media_type": "special",
            "resolution": "1080p",
            "source": "BDRip",
        },
        id="SP带编号",
    ),
    pytest.param(
        "[Group] 某作品OVA [1080p]",
        {
            "title_zh": "某作品",
            "group": "Group",
            "media_type": "ova",
            "resolution": "1080p",
        },
        id="OVA粘连中文标题",
    ),
    pytest.param(
        "[Official] Anime Title PV2 [1080p]",
        {
            "title_en": "Anime Title",
            "group": "Official",
            "episode": 2,
            "media_type": "pv",
            "resolution": "1080p",
        },
        id="PV带编号",
    ),
    pytest.param(
        "[VCB-Studio] Anime Title NCOP [BDRip 1080p]",
        {
            "title_en": "Anime Title",
            "group": "VCB-Studio",
            "media_type": "opening",
            "resolution": "1080p",
            "source": "BDRip",
        },
        id="NCOP片头",
    ),
    pytest.param(
        "[VCB-Studio] Anime Title NCED [BDRip 1080p]",
        {
            "title_en": "Anime Title",
            "group": "VCB-Studio",
            "media_type": "ending",
            "resolution": "1080p",
            "source": "BDRip",
        },
        id="NCED片尾",
    ),
    pytest.param(
        "[Group] Anime Title NCOPv2 [1080p]",
        {
            "title_en": "Anime Title",
            "group": "Group",
            "media_type": "opening",
            "resolution": "1080p",
            "version": 2,
        },
        id="NCOP版本号",
    ),
    pytest.param(
        "【幻樱字幕组】【4月新番】【古见同学有交流障碍症 第二季 "
        "Komi-san wa, Komyushou Desu. S02】【22】【GB_MP4】【1920X1080】",
        {
            "title_en": "Komi-san wa, Komyushou Desu.",
            "title_zh": "古见同学有交流障碍症",
            "group": "幻樱字幕组",
            "season": 2,
            "season_raw": "第二季",
            "episode": 22,
            "media_type": "episode",
            "resolution": "1920X1080",
            "subtitle": "GB",
            "container": "MP4",
            "tags": ["4月新番"],
        },
        id="全角方括号与新番前缀标签",
    ),
    pytest.param(
        "【极影字幕社】★4月新番 天国大魔境 Tengoku Daimakyou 第05话 GB 720P MP4"
        "（字幕社招人内详）",
        {
            "title_en": "Tengoku Daimakyou",
            "title_zh": "天国大魔境",
            "group": "极影字幕社",
            "episode": 5,
            "media_type": "episode",
            "resolution": "720P",
            "subtitle": "GB",
            "container": "MP4",
            "tags": ["★4月新番", "（字幕社招人内详）"],
        },
        id="中文第N话与招募标签",
    ),
    pytest.param(
        "[梦蓝字幕组]New Doraemon 哆啦A梦新番[747][2023.02.25][AVC][1080P]"
        "[GB_JP][MP4][101.69 MB]",
        {
            "title_en": "New Doraemon",
            "title_zh": "哆啦A梦新番",
            "group": "梦蓝字幕组",
            "episode": 747,
            "media_type": "episode",
            "resolution": "1080P",
            "subtitle": "GB_JP",
            "codecs": ["AVC"],
            "container": "MP4",
            "tags": ["2023.02.25", "101.69 MB"],
        },
        id="日期与文件大小入标签",
    ),
    pytest.param(
        "[Lilith-Raws] Otonari no Tenshi-sama - 09 "
        "[Baha][WEB-DL][1080p][AVC AAC][CHT][MP4].mkv",
        {
            "title_en": "Otonari no Tenshi-sama",
            "group": "Lilith-Raws",
            "episode": 9,
            "media_type": "episode",
            "resolution": "1080p",
            "source": "Baha",
            "subtitle": "CHT",
            "codecs": ["AVC"],
            "audio": ["AAC"],
            "container": "MP4",
        },
        id="后缀mkv被剥离",
    ),
    pytest.param(
        "Mob Psycho 100 - S03E05 - Divine Tree 2 ~Peace~ [1080p]",
        {
            "title_en": "Mob Psycho 100",
            "season": 3,
            "season_raw": "S03E05",
            "episode": 5,
            "episode_title": "Divine Tree 2 ~Peace~",
            "media_type": "episode",
            "resolution": "1080p",
        },
        id="Plex式集标题分离",
    ),
    pytest.param(
        "[VCB-Studio] Kimi no Na wa. (2016) [BDRip 1080p]",
        {
            "title_en": "Kimi no Na wa.",
            "group": "VCB-Studio",
            "resolution": "1080p",
            "source": "BDRip",
            "year": 2016,
        },
        id="圆括号年份",
    ),
    pytest.param(
        "[Group] 劇場版 呪術廻戦 0 [1080p]",
        {
            "title_zh": "呪術廻戦 0",
            "group": "Group",
            "media_type": "movie",
            "resolution": "1080p",
        },
        id="劇場版中文电影",
    ),
    pytest.param(
        "[VCB-Studio]电影版哆啦A梦：大雄的地球交响乐[BDRip 1080p]",
        {
            "title_zh": "哆啦A梦：大雄的地球交响乐",
            "group": "VCB-Studio",
            "media_type": "movie",
            "resolution": "1080p",
            "source": "BDRip",
        },
        id="电影版粘连中文标题",
    ),
    pytest.param(
        "[Group] Gekijouban Anime Title [1080p]",
        {
            "title_en": "Anime Title",
            "group": "Group",
            "media_type": "movie",
            "resolution": "1080p",
        },
        id="Gekijouban罗马字电影",
    ),
    pytest.param(
        "[Movie-Fan] Ordinary Anime - 01 [WEB-DL 1080p]",
        {
            "title_en": "Ordinary Anime",
            "group": "Movie-Fan",
            "episode": 1,
            "media_type": "episode",
            "resolution": "1080p",
            "source": "WEB-DL",
        },
        id="组名含Movie不误判",
    ),
    pytest.param(
        "[SubGroup] The Movie Star Next Door - 03 [WEB-DL 1080p]",
        {
            "title_en": "The Movie Star Next Door",
            "group": "SubGroup",
            "episode": 3,
            "media_type": "episode",
            "resolution": "1080p",
            "source": "WEB-DL",
        },
        id="标题含Movie不误判",
    ),
    pytest.param(
        "[SubGroup] Ranma 1/2 - 03 [WEB-DL 1080p]",
        {
            "title_en": "Ranma 1/2",
            "group": "SubGroup",
            "episode": 3,
            "media_type": "episode",
            "resolution": "1080p",
            "source": "WEB-DL",
        },
        id="标题内数字斜杠不拆分",
    ),
    pytest.param(
        "[Group] PV=nRT - 01 [1080p]",
        {
            "title_en": "PV=nRT",
            "group": "Group",
            "episode": 1,
            "media_type": "episode",
            "resolution": "1080p",
        },
        id="标题含PV不误判",
    ),
    pytest.param(
        "[Group] 86 - 01 [1080p]",
        {
            "title_en": "86",
            "group": "Group",
            "episode": 1,
            "media_type": "episode",
            "resolution": "1080p",
        },
        id="纯数字标题86",
    ),
    pytest.param(
        "[Group] Dandadan 2nd Season - 01 [1080p]",
        {
            "title_en": "Dandadan",
            "group": "Group",
            "season": 2,
            "season_raw": "2nd Season",
            "episode": 1,
            "media_type": "episode",
            "resolution": "1080p",
        },
        id="序数词季度2ndSeason",
    ),
    pytest.param(
        "[Group] 某作品 第二季 - 08 [1080p]",
        {
            "title_zh": "某作品",
            "group": "Group",
            "season": 2,
            "season_raw": "第二季",
            "episode": 8,
            "media_type": "episode",
            "resolution": "1080p",
        },
        id="中文第二季",
    ),
    pytest.param(
        "[Group] Anime Title [01 1080p HEVC]",
        {
            "title_en": "Anime Title",
            "group": "Group",
            "episode": 1,
            "media_type": "episode",
            "resolution": "1080p",
            "codecs": ["HEVC"],
        },
        id="集数混在技术方括号内",
    ),
    pytest.param(
        "[MOVIE] Anime Title [1080p]",
        {
            "title_en": "Anime Title",
            "media_type": "movie",
            "resolution": "1080p",
        },
        id="方括号MOVIE标记",
    ),
    pytest.param(
        "[LoliHouse] Sousou no Frieren [WEB-DL 1080p]",
        {
            "title_en": "Sousou no Frieren",
            "group": "LoliHouse",
            "resolution": "1080p",
            "source": "WEB-DL",
        },
        id="无集数仍解析标题",
    ),
    pytest.param("[1080p][HEVC][AAC][MKV]", None, id="负样本_纯技术标签"),
    pytest.param("[A1B2C3D4][1.2 GiB][2023-01-12]", None, id="负样本_哈希体积日期"),
]


@pytest.mark.parametrize("raw, expected", _CASES)
def test_parser_matches_golden_samples(raw, expected):
    parsed = parse_release_title(raw)

    if expected is None:
        assert parsed is None
        return

    assert parsed is not None
    assert parsed.raw == raw
    assert set(_DEFAULTS) <= {field.name for field in fields(parsed)}
    assert _snapshot(parsed) == {**_DEFAULTS, **expected}


def test_evidence_records_decision_sources():
    parsed = parse_release_title("[LoliHouse] Sousou no Frieren - 03 [1080p]")
    assert "group" in parsed.evidence
    assert "episode" in parsed.evidence
    assert "resolution" in parsed.evidence


@pytest.mark.parametrize("raw", ["", "   ", "\n"])
def test_blank_input_returns_none(raw):
    assert parse_release_title(raw) is None


def test_normalize_rewrites_fullwidth_brackets_and_strips_extension():
    assert normalize("【组】标题.mp4") == "[组]标题"
    assert normalize("A\nB") == "A B"
