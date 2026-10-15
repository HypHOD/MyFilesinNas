import logging

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import SQLModel

# 导入模型确保建表前元数据已注册
from module.models import Bangumi, RSSItem, Torrent  # noqa: F401

from .bangumi import BangumiDatabase
from .engine import async_engine, async_session_factory
from .rss import RSSDatabase
from .torrent import TorrentDatabase

logger = logging.getLogger(__name__)


class Database:
    """异步数据库 一次操作一个 session。
    session 只在 with 块内存活，绝不挂在长生命周期对象上。
    """

    def __init__(self, engine=None):
        # engine 是测试注入口；生产始终使用全局 session 工厂
        if engine is None:
            self.session: AsyncSession = async_session_factory()
        else:
            self.session = AsyncSession(engine, expire_on_commit=False)
        self.rss = RSSDatabase(self.session)
        self.torrent = TorrentDatabase(self.session)
        self.bangumi = BangumiDatabase(self.session)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.session.close()

    # 直接操作 session 的透传方法
    def add(self, obj):
        self.session.add(obj)

    async def commit(self):
        await self.session.commit()

    async def rollback(self):
        await self.session.rollback()

    async def refresh(self, obj):
        await self.session.refresh(obj)

    async def close(self):
        await self.session.close()

    async def create_table(self):
        async with async_engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)

    async def drop_table(self):
        async with async_engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.drop_all)
