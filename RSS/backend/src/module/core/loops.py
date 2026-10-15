"""周期任务的单次 tick 逻辑。

每个函数就是参考实现循环体的内容，去掉 ``self`` 依赖、改为显式参数注入。
异常由 :class:`~module.core.scheduler.PeriodicTask` 统一捕获并记录，这里
不再包顶层 try——唯一例外是 aggregate 源逐个扫描：单个坏源不应中断其余源
与整轮刷新；投递个别失败由 RSSEngine 内部处理（下轮自然重试）。
"""

import logging

from module.database import Database
from module.downloader import DownloadClient
from module.manager import Renamer
from module.rss import RSSAnalyser, RSSEngine

logger = logging.getLogger(__name__)


async def rss_tick(analyser: RSSAnalyser) -> None:
    """扫描 aggregate 源建立新订阅，然后跑一轮 拉取 → 匹配 → 投递。"""
    async with DownloadClient() as client:
        async with Database() as db:
            engine = RSSEngine(db)
            for rss in await db.rss.search_aggregate():
                try:
                    await analyser.rss_to_data(rss, engine)
                except Exception:
                    logger.warning(
                        "Error analysing RSS id=%s (%s)",
                        rss.id,
                        rss.url,
                        exc_info=True,
                    )
            await engine.refresh_rss(client)


async def rename_tick() -> None:
    """轮询已完成种子，重命名并打 ``ab:renamed`` 标记。"""
    async with DownloadClient() as client:
        async with Database() as db:
            await Renamer(client, db).rename()
