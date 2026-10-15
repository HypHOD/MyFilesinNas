"""torrent_parser 文件名解析测试。

样本取自参考实现的真实用例；两处适配差异：movie 分支已砍（相关用例不迁移），
未知字幕语言返回 None 而非抛 ValidationError。
"""

import sys

import pytest

from module.parser.analyser.torrent_parser import TorrentParser, get_path_basename

ISSUE_1072_TITLE = (
    "[SubsPlease] Haibara-kun no Tsuyokute Seishun New Game - 06v2 "
    "(1080p) [E931DD98].mkv"
)

MEDIA_CASES = [
    pytest.param(
        "[Lilith-Raws] Boku no Kokoro no Yabai Yatsu - 01"
        " [Baha][WEB-DL][1080p][AVC AAC][CHT][MP4].mp4",
        {
            "title": "Boku no Kokoro no Yabai Yatsu",
            "group": "Lilith-Raws",
            "season": 1,
            "episode": 1,
        },
        {},
        id="横线集数",
    ),
    pytest.param(
        "[Sakurato] Tonikaku Kawaii S2 [01][AVC-8bit 1080p AAC][CHS].mp4",
        {
            "title": "Tonikaku Kawaii",
            "group": "Sakurato",
            "season": 2,
            "episode": 1,
        },
        {},
        id="标题内季号",
    ),
    pytest.param(
        "[SweetSub&LoliHouse] Heavenly Delusion - 01"
        " [WebRip 1080p HEVC-10bit AAC ASSx2].mkv",
        {
            "title": "Heavenly Delusion",
            "group": "SweetSub&LoliHouse",
            "season": 1,
            "episode": 1,
        },
        {},
        id="含&联合字幕组",
    ),
    pytest.param(
        "[SBSUB][CONAN][1082][V2][1080P][AVC_AAC][CHS_JP](C1E4E331).mp4",
        {"title": "CONAN", "group": "SBSUB", "season": 1, "episode": 1082},
        {},
        id="千集长篇",
    ),
    pytest.param(
        "海盗战记 (2019) S01E01.mp4",
        {"title": "海盗战记 (2019)", "group": None, "season": 1, "episode": 1},
        {},
        id="括号年份保留进标题",
    ),
    pytest.param(
        "海盗战记/海盗战记 S01E01.mp4",
        {"title": "海盗战记", "group": None, "season": 1, "episode": 1},
        {},
        id="路径取 basename",
    ),
    pytest.param(
        "水星的魔女(2022) S00E19.mp4",
        {"title": "水星的魔女(2022)", "group": None, "season": 0, "episode": 19},
        {"season": 0},
        id="S00 特别季",
    ),
    pytest.param(
        "【失眠搬运组】放学后失眠的你-Kimi wa Houkago Insomnia - 06"
        " [bilibili - 1080p AVC1 CHS-JP].mp4",
        {
            "title": "放学后失眠的你-Kimi wa Houkago Insomnia",
            "group": "失眠搬运组",
            "season": 1,
            "episode": 6,
        },
        {"season": 1},
        id="全角括号组名",
    ),
    pytest.param(
        "不时用俄语小声说真心话的邻桌艾莉同学 S01E02.mp4",
        {
            "title": "不时用俄语小声说真心话的邻桌艾莉同学",
            "group": None,
            "season": 1,
            "episode": 2,
        },
        {},
        id="纯中文长标题",
    ),
    pytest.param(
        "[ANi] 關於我轉生變成史萊姆這檔事 第三季 - 48.5"
        " [1080P][Baha][WEB-DL][AAC AVC][CHT].mp4",
        {
            "title": "關於我轉生變成史萊姆這檔事 第三季",
            "group": "ANi",
            "season": 3,
            "episode": 48.5,
        },
        {"season": 3},
        id="小数半集",
    ),
    pytest.param(
        "[Ohys-Raws] Kamen Rider Gaim EP33 (TV-Asahi 1280x720 x264 AAC).mp4",
        {"title": "Kamen Rider Gaim", "group": "Ohys-Raws", "season": 1, "episode": 33},
        {},
        id="EP 前缀集数",
    ),
    pytest.param(
        "[Sakurato] Kaguya-sama wa Kokurasetai [12v2][AVC-8bit 1080p AAC][CHS].mp4",
        {
            "title": "Kaguya-sama wa Kokurasetai",
            "group": "Sakurato",
            "season": 1,
            "episode": 12,
        },
        {},
        id="方括号 v2 集数",
    ),
    pytest.param(
        ISSUE_1072_TITLE,
        {
            "title": "Haibara-kun no Tsuyokute Seishun New Game",
            "group": "SubsPlease",
            "season": 1,
            "episode": 6,
        },
        {},
        id="横线 v2 优先于 CRC 后缀",
    ),
    pytest.param(
        "/downloads/Bangumi/葬送的芙莉莲 (2023)/Season 1/葬送的芙莉莲 S01E05.mp4",
        {"title": "葬送的芙莉莲", "group": None, "season": 1, "episode": 5},
        {},
        id="绝对多层路径",
    ),
]

SUBTITLE_CASES = [
    pytest.param(
        "海盗战记 S01E01.zh-tw.ass",
        {
            "title": "海盗战记",
            "season": 1,
            "episode": 1,
            "language": "zh-tw",
            "suffix": ".ass",
        },
        {},
        id="zh-tw 后缀",
    ),
    pytest.param(
        "海盗战记 S01E01.SC.ass",
        {"title": "海盗战记", "season": 1, "episode": 1, "language": "zh"},
        {},
        id="SC 简中",
    ),
    pytest.param(
        "[ANi] 關於我轉生變成史萊姆這檔事 第三季 - 48.5"
        " [1080P][Baha][WEB-DL][AAC AVC][CHT].srt",
        {
            "title": "關於我轉生變成史萊姆這檔事 第三季",
            "season": 3,
            "episode": 48.5,
            "language": "zh-tw",
            "suffix": ".srt",
        },
        {"season": 3},
        id="CHT 繁体",
    ),
    pytest.param(
        "葬送的芙莉莲 S01E05.tc.ass",
        {"title": "葬送的芙莉莲", "season": 1, "episode": 5, "language": "zh-tw"},
        {},
        id="tc 视为繁体",
    ),
]


@pytest.mark.parametrize("raw, expected, kwargs", MEDIA_CASES)
def test_parse_media_file(raw, expected, kwargs):
    parsed = TorrentParser.parse_media_file(raw, **kwargs)
    assert parsed is not None, raw
    for field, value in expected.items():
        assert getattr(parsed, field) == value, f"{raw} 的 {field}"


@pytest.mark.parametrize("raw, expected, kwargs", SUBTITLE_CASES)
def test_parse_subtitle_file(raw, expected, kwargs):
    parsed = TorrentParser.parse_subtitle_file(raw, **kwargs)
    assert parsed is not None, raw
    for field, value in expected.items():
        assert getattr(parsed, field) == value, f"{raw} 的 {field}"


def test_parse_media_file_uses_torrent_name_first():
    parsed = TorrentParser.parse_media_file(
        "/downloads/abc123/unknown.mp4",
        torrent_name="[Group] Some Anime - 03 [1080p].mp4",
    )
    assert parsed is not None
    assert parsed.title == "Some Anime"
    assert parsed.group == "Group"
    assert parsed.episode == 3


def test_episode_keeps_int_or_float():
    parsed = TorrentParser.parse_media_file(
        "[Lilith-Raws] Boku no Kokoro no Yabai Yatsu - 01"
        " [Baha][WEB-DL][1080p][AVC AAC][CHT][MP4].mp4"
    )
    assert parsed is not None
    assert isinstance(parsed.episode, int)
    parsed = TorrentParser.parse_media_file(
        "[ANi] 關於我轉生變成史萊姆這檔事 第三季 - 48.5"
        " [1080P][Baha][WEB-DL][AAC AVC][CHT].mp4",
        season=3,
    )
    assert parsed is not None
    assert isinstance(parsed.episode, float)


def test_media_without_episode_marker_returns_none():
    assert TorrentParser.parse_media_file("天气之子 (2019) [1080p].mp4") is None


def test_subtitle_with_unknown_language_returns_none():
    assert TorrentParser.parse_subtitle_file("Dungeon Meshi S01E01.srt") is None


class TestGetPathBasename:
    def test_regular_path(self):
        assert get_path_basename("/path/to/file.txt") == "file.txt"

    def test_empty_path(self):
        assert get_path_basename("") == ""

    def test_path_with_trailing_slash(self):
        assert get_path_basename("/path/to/folder/") == "folder"

    @pytest.mark.skipif(not sys.platform.startswith("win"), reason="仅 Windows")
    def test_windows_path(self):
        assert get_path_basename("C:\\path\\to\\file.txt") == "file.txt"
