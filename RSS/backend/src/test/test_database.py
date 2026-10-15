import pytest

from module.database import Database
from module.database.bangumi import _groups_are_similar, match_bangumi_in_list
from module.models import Bangumi, BangumiUpdate, RSSItem, RSSUpdate, Torrent


async def test_rss_crud(db_engine):
    async with Database(engine=db_engine) as db:
        item = await db.rss.add(RSSItem(name="Mikan", url="https://mikanani.me/RSS"))
        assert item.id is not None
        assert len(await db.rss.search_all()) == 1
        assert await db.rss.search_url("https://mikanani.me/RSS") is not None

        assert await db.rss.disable(item.id)
        assert await db.rss.search_active() == []
        assert await db.rss.enable(item.id)
        assert len(await db.rss.search_active()) == 1

        assert await db.rss.update(item.id, RSSUpdate(name="New"))
        assert (await db.rss.search_id(item.id)).name == "New"

        assert await db.rss.delete(item.id)
        assert await db.rss.search_all() == []


async def test_bangumi_crud_and_soft_delete(db_engine):
    async with Database(engine=db_engine) as db:
        b = await db.bangumi.add(
            Bangumi(official_title="测试番剧", title_raw="Test Anime")
        )
        assert b.id is not None
        assert len(await db.bangumi.search_all()) == 1

        updated = await db.bangumi.update(b.id, BangumiUpdate(episode_offset=12))
        assert updated.episode_offset == 12

        # 软删除后列表不可见，但数据仍在
        assert await db.bangumi.disable_rule(b.id)
        assert await db.bangumi.search_all() == []
        assert (await db.bangumi.search_id(b.id)).deleted is True


async def test_torrent_check_new(db_engine):
    async with Database(engine=db_engine) as db:
        await db.torrent.add(Torrent(name="ep1", url="https://example.com/1"))
        new = await db.torrent.check_new(
            [
                Torrent(name="ep1", url="https://example.com/1"),
                Torrent(name="ep2", url="https://example.com/2"),
            ]
        )
        assert [t.url for t in new] == ["https://example.com/2"]


async def test_rss_search_aggregate(db_engine):
    async with Database(engine=db_engine) as db:
        await db.rss.add(RSSItem(name="自动", url="https://x/1", aggregate=True))
        await db.rss.add(
            RSSItem(name="停用", url="https://x/2", aggregate=True, enabled=False)
        )
        await db.rss.add(RSSItem(name="手动", url="https://x/3"))
        found = await db.rss.search_aggregate()
        assert [r.name for r in found] == ["自动"]


async def test_rss_update_connection_status(db_engine):
    async with Database(engine=db_engine) as db:
        item = await db.rss.add(RSSItem(name="Mikan", url="https://mikanani.me/RSS"))
        ok = await db.rss.update_connection_status(
            item.id, "healthy", "2026-10-15T12:00:00"
        )
        assert ok
        await db.rss.update_connection_status(
            item.id, "error", "2026-10-15T12:01:00", error="timeout"
        )
        refreshed = await db.rss.search_id(item.id)
        assert refreshed.connection_status == "error"
        assert refreshed.last_checked_at == "2026-10-15T12:01:00"
        assert refreshed.last_error == "timeout"
        assert await db.rss.update_connection_status(999, "healthy", "t") is False


# ------------------------------------------------------ match_bangumi_in_list


def _bangumi(**kwargs) -> Bangumi:
    kwargs.setdefault("season", 1)
    return Bangumi(**kwargs)


def test_typed_bangumi_identities_can_coexist_and_match():
    shared = dict(
        official_title="Shared Anime",
        title_raw="Shared Anime",
        group_name="Group",
    )
    episode = Bangumi(**shared, season=1, episode_type="episode")
    season_two = Bangumi(**shared, season=2, episode_type="episode")
    special = Bangumi(**shared, season=0, episode_type="special")
    rows = [episode, season_two, special]

    matched_s2 = match_bangumi_in_list("[Group] Shared Anime S02E01 [1080p]", rows)
    matched_ova = match_bangumi_in_list("[Group] Shared Anime OVA01 [1080p]", rows)
    matched_episode = match_bangumi_in_list("[Group] Shared Anime - 01 [1080p]", rows)

    assert matched_s2 is season_two
    assert matched_ova is special
    assert matched_episode is not None and matched_episode.episode_type == "episode"


@pytest.mark.parametrize(
    ("raw", "pattern"),
    (
        ("[Group] Shared Anime [TV 01-12 + OVA 01-02] [1080p]", "Shared Anime"),
        ("[Group] Anime Complete Batch [1080p]", "Anime"),
        ("[Group] Anime 合集 [1080p]", "Anime"),
    ),
)
def test_non_single_release_does_not_match(raw, pattern):
    """区间/批次/合集不是可订阅的单集正片，即使标题命中也不匹配。"""
    bangumi = _bangumi(
        official_title=pattern, title_raw=pattern, group_name="Group", season=1
    )
    assert match_bangumi_in_list(raw, [bangumi]) is None


def test_weak_title_only_release_does_not_match():
    bangumi = _bangumi(official_title="Some Random Text", title_raw="Some Random Text")
    assert match_bangumi_in_list("Some Random Text", [bangumi]) is None


def test_deleted_bangumi_is_skipped():
    bangumi = _bangumi(
        official_title="Anime", title_raw="Anime", group_name="Group", deleted=True
    )
    assert match_bangumi_in_list("[Group] Anime - 01 [1080p]", [bangumi]) is None


def test_season_mismatch_is_rejected():
    bangumi = _bangumi(official_title="Anime", title_raw="Anime", group_name="Group")
    assert match_bangumi_in_list("[Group] Anime S02E01 [1080p]", [bangumi]) is None


def test_longest_pattern_wins():
    generic = _bangumi(
        official_title="Shared Anime", title_raw="Shared Anime", season=2
    )
    specific = _bangumi(
        official_title="Shared Anime", title_raw="Shared Anime S02", season=2
    )
    matched = match_bangumi_in_list(
        "[Group] Shared Anime S02E01 [1080p]", [generic, specific]
    )
    assert matched is specific


def test_group_similarity_breaks_tie():
    other = _bangumi(official_title="Anime", title_raw="Anime", group_name="Sakurato")
    ours = _bangumi(
        official_title="Anime",
        title_raw="Anime",
        group_name="LoliHouse&动漫国字幕组",
    )
    matched = match_bangumi_in_list("[LoliHouse] Anime - 05 [1080p]", [other, ours])
    assert matched is ours


@pytest.mark.parametrize(
    ("title_raw", "raw"),
    (
        # #1103：集数从标题中间被剔除后，title_raw 不再是种子名的子串
        (
            "攻壳机动队「攻壳机动队 THE GHOST IN THE SHELL」 日英双语-多国字幕",
            "攻壳机动队「攻壳机动队 THE GHOST IN THE SHELL」 S01E03 1080p 日英双语-多国字幕",
        ),
        # #1114：" / " 分隔的多个英文名被拼接进 title_raw
        (
            "20 Seiki Denki Mokuroku Nijusseiki Denki Mokuroku",
            "[喵萌奶茶屋&LoliHouse] 二十世纪电气目录 / 20 Seiki Denki Mokuroku / "
            "Nijusseiki Denki Mokuroku - 07 [WebRip 1080p HEVC-10bit AAC][简繁日内封字幕]",
        ),
    ),
)
def test_reconstructed_title_raw_equality_matches(title_raw, raw):
    """title_raw 非种子名子串时，与解析器重组出的标题完全相等也算命中。"""
    bangumi = _bangumi(official_title=title_raw, title_raw=title_raw)
    assert match_bangumi_in_list(raw, [bangumi]) is bangumi


def test_groups_are_similar():
    assert _groups_are_similar("LoliHouse", "LoliHouse") is True
    assert _groups_are_similar("LoliHouse", "LoliHouse&动漫国字幕组") is True
    assert _groups_are_similar("LoliHouse&动漫国字幕组", "LoliHouse") is True
    # 归一化命中：去掉分隔符并忽略大小写后一致
    assert _groups_are_similar("LoliHouse-HD", "lolihouse_hd") is True
    assert _groups_are_similar("LoliHouse", "Sakurato") is False
    assert _groups_are_similar("字幕组A", "字幕组B") is False
    assert _groups_are_similar(None, "LoliHouse") is False
    assert _groups_are_similar("LoliHouse", None) is False
    assert _groups_are_similar(None, None) is False
