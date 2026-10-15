from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from module.models import RSSItem, RSSUpdate


class RSSDatabase:
    """RSS 订阅源表操作。所有方法自带 commit, 调用方无需再提交。"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def add(self, data: RSSItem) -> RSSItem:
        self.session.add(data)
        await self.session.commit()
        await self.session.refresh(data)
        return data

    async def search_all(self) -> list[RSSItem]:
        result = await self.session.execute(select(RSSItem))
        return list(result.scalars().all())

    async def search_active(self) -> list[RSSItem]:
        result = await self.session.execute(
            select(RSSItem).where(RSSItem.enabled == True)  # noqa: E712
        )
        return list(result.scalars().all())

    async def search_aggregate(self) -> list[RSSItem]:
        """启用且开启「解析种子发现新番」的订阅源。"""
        result = await self.session.execute(
            select(RSSItem).where(
                RSSItem.aggregate == True,  # noqa: E712
                RSSItem.enabled == True,  # noqa: E712
            )
        )
        return list(result.scalars().all())

    async def update_connection_status(
        self, rss_id: int, status: str, checked_at: str, error: str | None = None
    ) -> bool:
        """回写一次拉取后的连接状态。

        运行态字段（connection_status/last_checked_at/last_error）只能经此
        方法更新，不走 RSSUpdate——那是 PATCH 载荷，不允许 API 直接写状态。
        """
        rss = await self.search_id(rss_id)
        if rss is None:
            return False
        rss.connection_status = status
        rss.last_checked_at = checked_at
        rss.last_error = error
        self.session.add(rss)
        await self.session.commit()
        return True

    async def search_id(self, rss_id: int) -> RSSItem | None:
        return await self.session.get(RSSItem, rss_id)

    async def search_url(self, url: str) -> RSSItem | None:
        result = await self.session.execute(select(RSSItem).where(RSSItem.url == url))
        return result.scalars().first()

    async def update(self, rss_id: int, data: RSSUpdate) -> bool:
        rss = await self.search_id(rss_id)
        if rss is None:
            return False
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(rss, key, value)
        self.session.add(rss)
        await self.session.commit()
        return True

    async def enable(self, rss_id: int) -> bool:
        return await self._set_enabled(rss_id, True)

    async def disable(self, rss_id: int) -> bool:
        return await self._set_enabled(rss_id, False)

    async def _set_enabled(self, rss_id: int, enabled: bool) -> bool:
        rss = await self.search_id(rss_id)
        if rss is None:
            return False
        rss.enabled = enabled
        self.session.add(rss)
        await self.session.commit()
        return True

    async def delete(self, rss_id: int) -> bool:
        rss = await self.search_id(rss_id)
        if rss is None:
            return False
        await self.session.delete(rss)
        await self.session.commit()
        return True
