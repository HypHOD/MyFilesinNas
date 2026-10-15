from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from module.models import Torrent


class TorrentDatabase:
    """种子记录表操作。所有方法自带 commit, 调用方无需再提交。"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def add(self, data: Torrent) -> Torrent:
        self.session.add(data)
        await self.session.commit()
        await self.session.refresh(data)
        return data

    async def add_all(self, datas: list[Torrent]) -> list[Torrent]:
        self.session.add_all(datas)
        await self.session.commit()
        return datas

    async def search_all(self) -> list[Torrent]:
        result = await self.session.execute(select(Torrent))
        return list(result.scalars().all())

    async def search_by_url(self, url: str) -> Torrent | None:
        result = await self.session.execute(select(Torrent).where(Torrent.url == url))
        return result.scalars().first()

    async def search_by_qb_hash(self, qb_hash: str) -> Torrent | None:
        result = await self.session.execute(
            select(Torrent).where(Torrent.qb_hash == qb_hash)
        )
        return result.scalars().first()

    async def check_new(self, torrents: list[Torrent]) -> list[Torrent]:
        """返回库中不存在的种子（按 url 去重），RSS 去重的第一道防线。"""
        result = await self.session.execute(select(Torrent.url))
        exist = {row[0] for row in result.all()}
        return [t for t in torrents if t.url not in exist]

    async def update_downloaded(self, torrent_id: int, downloaded: bool) -> bool:
        torrent = await self.session.get(Torrent, torrent_id)
        if torrent is None:
            return False
        torrent.downloaded = downloaded
        self.session.add(torrent)
        await self.session.commit()
        return True
