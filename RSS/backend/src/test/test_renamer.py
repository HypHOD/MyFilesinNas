"""Renamer 测试：gen_path 表驱动 + MockDownloader 全链。

覆盖：补零/半集小数/集数偏移三保护、`ab:renamed` 幂等（二次运行跳过）、
自愈（文件已是目标名补打标签）、合集全成才打标且失败可重试、字幕随正片
一起改名、偏移反查（标签 / qb_hash 回退）。
"""

import pytest

from module.database import Database
from module.downloader import DownloadClient
from module.downloader.base import RenameOutcome, RenameResult
from module.manager import Renamer
from module.models import Bangumi, EpisodeFile, SubtitleFile, Torrent

TORRENT_ITEM = "[LoliHouse] 葬送的芙莉莲 - 05 [1080p].mkv"
SAVE_PATH = "/downloads/Bangumi/葬送的芙莉莲/Season 1"


def media_info(
    season: int = 1,
    episode: int | float = 5,
    title: str = "葬送的芙莉莲",
    suffix: str = ".mkv",
) -> EpisodeFile:
    return EpisodeFile(
        media_path=f"[LoliHouse] {title} - {episode} [1080p]{suffix}",
        title=title,
        season=season,
        episode=episode,
        suffix=suffix,
    )


# ---------------------------------------------------------------- gen_path


@pytest.mark.parametrize(
    "season,episode,episode_offset,expected",
    [
        (1, 5, 0, "葬送的芙莉莲 S01E05.mkv"),
        # 两位数季号不补零、不补零的集数不加前缀
        (2, 12, 0, "葬送的芙莉莲 S02E12.mkv"),
        (10, 1, 0, "葬送的芙莉莲 S10E01.mkv"),
        # 总集篇半集保留小数 (#667)；float 整数值折回 int
        (1, 12.5, 0, "葬送的芙莉莲 S01E12.5.mkv"),
        (1, 5.0, 0, "葬送的芙莉莲 S01E05.mkv"),
        # 集数偏移三保护
        (1, 5, 2, "葬送的芙莉莲 S01E07.mkv"),
        (1, 5, -2, "葬送的芙莉莲 S01E03.mkv"),
        (1, 2, -10, "葬送的芙莉莲 S01E02.mkv"),
        (1, 0, 3, "葬送的芙莉莲 S01E00.mkv"),
    ],
)
def test_gen_path_pn(season, episode, episode_offset, expected):
    info = media_info(season=season, episode=episode)
    assert Renamer.gen_path(info, "葬送的芙莉莲", "pn", episode_offset) == expected


def test_gen_path_passthrough_methods():
    info = media_info()
    # none 直通；normal 已废弃直通；未移植的方法（如 advance）记错误后直通
    assert Renamer.gen_path(info, "x", "none") == info.media_path
    assert Renamer.gen_path(info, "x", "normal") == info.media_path
    assert Renamer.gen_path(info, "x", "advance") == info.media_path


def test_gen_path_subtitle_pn_appends_language():
    sub = SubtitleFile(
        media_path="[LoliHouse] 葬送的芙莉莲 - 05 [1080p].zh-tw.ass",
        title="葬送的芙莉莲",
        season=1,
        episode=5,
        language="zh-tw",
        suffix=".ass",
    )
    assert Renamer.gen_path(sub, "x", "subtitle_pn") == "葬送的芙莉莲 S01E05.zh-tw.ass"
    assert Renamer.gen_path(sub, "x", "subtitle_none") == sub.media_path


@pytest.mark.parametrize(
    "original,episode_offset,expected",
    [
        (5, 0, 5),
        (5, 2, 7),
        (12.5, 0, 12.5),
        # EP0（特别篇/OVA）任何偏移都不动 (#977)
        (0, 3, 0),
        (0, 0, 0),
        # 偏移后非正：回退原集数并告警
        (2, -10, 2),
        (1, -1, 1),
    ],
)
def test_adjust_episode(original, episode_offset, expected):
    assert Renamer._adjust_episode(original, episode_offset) == expected


# ------------------------------------------------------------- 标签工具


@pytest.mark.parametrize(
    "tags,expected",
    [
        (["ab:3", "other"], 3),
        ("ab:3, other", 3),
        (["other", "ab:7"], 7),
        ("ab:xyz", None),
        ("ab:", None),
        ("other", None),
        (None, None),
        ([], None),
    ],
)
def test_parse_bangumi_id_from_tags(tags, expected):
    assert Renamer(client=None, db=None)._parse_bangumi_id_from_tags(tags) == expected


@pytest.mark.parametrize(
    "tags,found",
    [
        (["ab:renamed", "x"], True),
        ("x,ab:renamed", True),
        ("x, ab:renamed", True),
        ("other", False),
        (["other"], False),
        (None, False),
    ],
)
def test_has_tag_handles_list_and_string(tags, found):
    assert Renamer(client=None, db=None)._has_tag(tags, "ab:renamed") is found


# ------------------------------------------------------------- 全链（mock）


async def test_rename_single_file_and_second_run_skipped(
    db_engine, mock_downloader_settings
):
    async with Database(engine=db_engine) as db:
        await db.bangumi.add(
            Bangumi(official_title="葬送的芙莉莲", title_raw="葬送的芙莉莲")
        )
        async with DownloadClient() as client:
            client.client.add_mock_torrent(
                name=TORRENT_ITEM,
                save_path=SAVE_PATH,
                files=[{"name": TORRENT_ITEM}],
            )
            renamer = Renamer(client, db)

            await renamer.rename()
            (torrent,) = client.client.get_state()["torrents"].values()
            assert [f["name"] for f in torrent["files"]] == ["葬送的芙莉莲 S01E05.mkv"]
            assert "ab:renamed" in torrent["tags"]

            # 二次运行：已带 ab:renamed → 整颗种子直接跳过
            await renamer.rename()
            assert [f["name"] for f in torrent["files"]] == ["葬送的芙莉莲 S01E05.mkv"]


async def test_rename_applies_offset_from_tag(db_engine, mock_downloader_settings):
    async with Database(engine=db_engine) as db:
        bangumi = await db.bangumi.add(
            Bangumi(
                official_title="葬送的芙莉莲",
                title_raw="葬送的芙莉莲",
                episode_offset=2,
            )
        )
        async with DownloadClient() as client:
            torrent_hash = client.client.add_mock_torrent(
                name=TORRENT_ITEM,
                save_path=SAVE_PATH,
                files=[{"name": TORRENT_ITEM}],
            )
            await client.client.add_tag(torrent_hash, f"ab:{bangumi.id}")

            await Renamer(client, db).rename()
            (torrent,) = client.client.get_state()["torrents"].values()
            assert [f["name"] for f in torrent["files"]] == ["葬送的芙莉莲 S01E07.mkv"]


async def test_rename_uses_offset_from_qb_hash_record(
    db_engine, mock_downloader_settings
):
    """种子名匹配不上订阅时，经 Torrent 表的 qb_hash 记录反查偏移量。"""
    other_item = "[LoliHouse] 别的番 - 05 [1080p].mkv"
    async with Database(engine=db_engine) as db:
        bangumi = await db.bangumi.add(
            Bangumi(
                official_title="葬送的芙莉莲",
                title_raw="葬送的芙莉莲",
                episode_offset=3,
            )
        )
        async with DownloadClient() as client:
            torrent_hash = client.client.add_mock_torrent(
                name=other_item,
                save_path=SAVE_PATH,
                files=[{"name": other_item}],
            )
            await db.torrent.add(
                Torrent(
                    bangumi_id=bangumi.id,
                    name=other_item,
                    url="https://x/qb-hash-record",
                    qb_hash=torrent_hash,
                )
            )

            await Renamer(client, db).rename()
            (torrent,) = client.client.get_state()["torrents"].values()
            assert [f["name"] for f in torrent["files"]] == ["别的番 S01E08.mkv"]


async def test_rename_season_comes_from_save_path_folder(
    db_engine, mock_downloader_settings
):
    async with Database(engine=db_engine) as db:
        await db.bangumi.add(
            Bangumi(official_title="葬送的芙莉莲", title_raw="葬送的芙莉莲")
        )
        async with DownloadClient() as client:
            client.client.add_mock_torrent(
                name=TORRENT_ITEM,
                save_path="/downloads/Bangumi/葬送的芙莉莲/Season 2",
                files=[{"name": TORRENT_ITEM}],
            )

            await Renamer(client, db).rename()
            (torrent,) = client.client.get_state()["torrents"].values()
            assert [f["name"] for f in torrent["files"]] == ["葬送的芙莉莲 S02E05.mkv"]


async def test_rename_self_heals_when_already_at_target(
    db_engine, mock_downloader_settings
):
    """改名成功但打标失败：下轮文件已是目标名，跳过改名直接补打标签。"""
    async with Database(engine=db_engine) as db:
        await db.bangumi.add(
            Bangumi(official_title="葬送的芙莉莲", title_raw="葬送的芙莉莲")
        )
        async with DownloadClient() as client:
            client.client.add_mock_torrent(
                name=TORRENT_ITEM,
                save_path=SAVE_PATH,
                files=[{"name": TORRENT_ITEM}],
            )
            renamer = Renamer(client, db)
            await renamer.rename()
            (torrent,) = client.client.get_state()["torrents"].values()
            torrent["tags"].remove("ab:renamed")

            await renamer.rename()
            assert [f["name"] for f in torrent["files"]] == ["葬送的芙莉莲 S01E05.mkv"]
            assert "ab:renamed" in torrent["tags"]


async def test_rename_collection_renames_all_then_tags(
    db_engine, mock_downloader_settings
):
    item_01 = "[LoliHouse] 葬送的芙莉莲 - 01 [1080p].mkv"
    item_02 = "[LoliHouse] 葬送的芙莉莲 - 02 [1080p].mkv"
    async with Database(engine=db_engine) as db:
        await db.bangumi.add(
            Bangumi(official_title="葬送的芙莉莲", title_raw="葬送的芙莉莲")
        )
        async with DownloadClient() as client:
            client.client.add_mock_torrent(
                name="[LoliHouse] 葬送的芙莉莲 合集 [1080p]",
                save_path=SAVE_PATH,
                files=[{"name": item_01}, {"name": item_02}],
            )

            await Renamer(client, db).rename()
            (torrent,) = client.client.get_state()["torrents"].values()
            assert sorted(f["name"] for f in torrent["files"]) == [
                "葬送的芙莉莲 S01E01.mkv",
                "葬送的芙莉莲 S01E02.mkv",
            ]
            assert "ab:renamed" in torrent["tags"]


async def test_rename_collection_partial_failure_withholds_tag_and_retries(
    db_engine, mock_downloader_settings, monkeypatch
):
    item_01 = "[LoliHouse] 葬送的芙莉莲 - 01 [1080p].mkv"
    item_02 = "[LoliHouse] 葬送的芙莉莲 - 02 [1080p].mkv"
    fail = {"value": True}
    async with Database(engine=db_engine) as db:
        await db.bangumi.add(
            Bangumi(official_title="葬送的芙莉莲", title_raw="葬送的芙莉莲")
        )
        async with DownloadClient() as client:
            client.client.add_mock_torrent(
                name="[LoliHouse] 葬送的芙莉莲 合集 [1080p]",
                save_path=SAVE_PATH,
                files=[{"name": item_01}, {"name": item_02}],
            )
            original = client.client.rename_torrent_file

            async def flaky(torrent_hash, old_path, new_path, verify=True):
                if fail["value"] and old_path == item_01:
                    return RenameResult(RenameOutcome.RETRYABLE_FAILURE, detail="boom")
                return await original(torrent_hash, old_path, new_path, verify=verify)

            monkeypatch.setattr(client.client, "rename_torrent_file", flaky)
            renamer = Renamer(client, db)

            # 任一失败：整体不打标（否则残缺合集永远不会重试）
            await renamer.rename()
            (torrent,) = client.client.get_state()["torrents"].values()
            names = {f["name"] for f in torrent["files"]}
            assert names == {item_01, "葬送的芙莉莲 S01E02.mkv"}
            assert "ab:renamed" not in torrent["tags"]

            # 下轮：已改好的文件跳过，失败的重试成功后才打标
            fail["value"] = False
            await renamer.rename()
            assert {f["name"] for f in torrent["files"]} == {
                "葬送的芙莉莲 S01E01.mkv",
                "葬送的芙莉莲 S01E02.mkv",
            }
            assert "ab:renamed" in torrent["tags"]


async def test_rename_subtitle_follows_media(db_engine, mock_downloader_settings):
    subtitle_item = "[LoliHouse] 葬送的芙莉莲 - 05 [1080p].zh-tw.ass"
    async with Database(engine=db_engine) as db:
        await db.bangumi.add(
            Bangumi(official_title="葬送的芙莉莲", title_raw="葬送的芙莉莲")
        )
        async with DownloadClient() as client:
            client.client.add_mock_torrent(
                name=TORRENT_ITEM,
                save_path=SAVE_PATH,
                files=[{"name": TORRENT_ITEM}, {"name": subtitle_item}],
            )

            await Renamer(client, db).rename()
            (torrent,) = client.client.get_state()["torrents"].values()
            assert {f["name"] for f in torrent["files"]} == {
                "葬送的芙莉莲 S01E05.mkv",
                "葬送的芙莉莲 S01E05.zh-tw.ass",
            }


async def test_rename_skips_uncompleted_torrent(db_engine, mock_downloader_settings):
    async with Database(engine=db_engine) as db:
        await db.bangumi.add(
            Bangumi(official_title="葬送的芙莉莲", title_raw="葬送的芙莉莲")
        )
        async with DownloadClient() as client:
            client.client.add_mock_torrent(
                name=TORRENT_ITEM,
                state="downloading",
                save_path=SAVE_PATH,
                files=[{"name": TORRENT_ITEM}],
            )

            await Renamer(client, db).rename()
            (torrent,) = client.client.get_state()["torrents"].values()
            assert [f["name"] for f in torrent["files"]] == [TORRENT_ITEM]
            assert "ab:renamed" not in torrent["tags"]
