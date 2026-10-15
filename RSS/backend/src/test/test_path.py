"""downloader.path 路径工具测试（样本取自参考实现的真实用例）。"""

import pytest

from module.downloader.path import (
    check_files,
    file_depth,
    gen_save_path,
    is_ep,
    path_to_bangumi,
    sanitize_path_fragment,
)
from module.models import Bangumi, BangumiUpdate

DOWNLOAD_ROOT = "/downloads/Bangumi"


@pytest.fixture(autouse=True)
def _fixed_download_root(monkeypatch):
    from module.conf import settings

    monkeypatch.setattr(settings.downloader, "path", DOWNLOAD_ROOT)


# ------------------------------------------------------------ gen_save_path


def test_gen_save_path_with_year():
    data = Bangumi(official_title="葬送的芙莉莲", year="2023", season=1)
    assert gen_save_path(data) == f"{DOWNLOAD_ROOT}/葬送的芙莉莲 (2023)/Season 1"


def test_gen_save_path_without_year():
    data = Bangumi(official_title="葬送的芙莉莲", season=1)
    assert gen_save_path(data) == f"{DOWNLOAD_ROOT}/葬送的芙莉莲/Season 1"


def test_gen_save_path_applies_season_offset():
    data = Bangumi(official_title="Anime", season=2, season_offset=1)
    assert gen_save_path(data).endswith("/Season 3")


def test_gen_save_path_offset_cancel_falls_back():
    # 偏移把普通剧集压到 Season 0 时回退原季号（否则会被当特别篇）
    data = Bangumi(official_title="Anime", season=1, season_offset=-1)
    assert gen_save_path(data).endswith("/Season 1")


def test_gen_save_path_special_allows_season_zero():
    data = Bangumi(official_title="Anime", season=0, episode_type="special")
    assert gen_save_path(data).endswith("/Season 0")


def test_gen_save_path_special_offset_clamps_to_zero():
    data = Bangumi(
        official_title="Anime", season=1, season_offset=-1, episode_type="special"
    )
    assert gen_save_path(data).endswith("/Season 0")


def test_gen_save_path_sanitizes_title():
    data = Bangumi(official_title="呪術廻戦:0/劇場版?", season=1)
    assert gen_save_path(data) == f"{DOWNLOAD_ROOT}/呪術廻戦 0 劇場版/Season 1"


def test_gen_save_path_all_illegal_title_falls_back():
    data = Bangumi(official_title="///", season=1)
    assert gen_save_path(data) == f"{DOWNLOAD_ROOT}/Unknown Bangumi/Season 1"


def test_gen_save_path_accepts_update_payload():
    data = BangumiUpdate(official_title="Anime", season=2, season_offset=0)
    assert gen_save_path(data) == f"{DOWNLOAD_ROOT}/Anime/Season 2"


# ---------------------------------------------------- sanitize_path_fragment


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("葬送的芙莉莲 (2023)", "葬送的芙莉莲 (2023)"),  # 已合法，幂等
        ('企鹅:"物流"|2024*', "企鹅 物流 2024"),
        ("Anime... ", "Anime"),
        ("a  b", "a b"),
    ],
)
def test_sanitize_path_fragment(raw, expected):
    assert sanitize_path_fragment(raw) == expected


# --------------------------------------------------------------- check_files


def test_check_files_splits_media_and_subtitles():
    files = [
        {"name": "Season 1/Anime S01E01.mkv"},
        {"name": "Season 1/Anime S01E01.MP4"},
        {"name": "Season 1/Anime S01E01.ass"},
        {"name": "Season 1/Anime S01E01.srt"},
        {"name": "readme.txt"},
    ]
    media, subtitles = check_files(files)
    assert media == ["Season 1/Anime S01E01.mkv", "Season 1/Anime S01E01.MP4"]
    assert subtitles == ["Season 1/Anime S01E01.ass", "Season 1/Anime S01E01.srt"]


# ------------------------------------------------------------ path_to_bangumi


def test_path_to_bangumi_posix():
    name, season = path_to_bangumi("/downloads/Bangumi/葬送的芙莉莲 (2023)/Season 2")
    assert (name, season) == ("葬送的芙莉莲 (2023)", 2)


def test_path_to_bangumi_windows_save_path():
    name, season = path_to_bangumi(r"C:\Downloads\Bangumi\Anime (2022)\Season 3")
    assert (name, season) == ("Anime (2022)", 3)


def test_path_to_bangumi_s_folder():
    name, season = path_to_bangumi("/downloads/Bangumi/Anime/S02")
    assert (name, season) == ("Anime", 2)


def test_path_to_bangumi_without_season_folder():
    assert path_to_bangumi("/downloads/Bangumi/Anime") == ("Anime", 1)


def test_path_to_bangumi_falls_back_to_torrent_name():
    assert path_to_bangumi(DOWNLOAD_ROOT, "Some Torrent") == ("Some Torrent", 1)


# --------------------------------------------------------- file_depth / is_ep


def test_file_depth_and_is_ep():
    assert file_depth("Anime S01E01.mkv") == 1
    assert file_depth("Season 1/Anime S01E01.mkv") == 2
    assert file_depth("a/b/c.mkv") == 3
    assert is_ep("Season 1/Anime S01E01.mkv")
    assert not is_ep("a/b/c.mkv")


def test_file_depth_handles_windows_separators():
    assert file_depth("Season 1\\Anime S01E01.mkv") == 2
