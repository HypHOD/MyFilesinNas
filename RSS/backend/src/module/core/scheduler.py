"""通用周期任务调度器。

``PeriodicTask`` 把「运行一次 tick，然后等待一个间隔」的循环抽象出来；
``Scheduler`` 负责批量启停这些任务。
"""

import asyncio
import logging
from typing import Awaitable, Callable

logger = logging.getLogger(__name__)


class PeriodicTask:
    """单个 asyncio 循环：运行 ``run`` 后等待 ``interval`` 秒，如此往复。

    * ``initial_delay > 0`` 时先等待再跑第一轮，否则立即跑第一轮；
    * ``interval`` 和 ``enabled`` 是**可调用对象**，每次读取当下值，
      因此配置变更无需重建任务即可生效；
    * tick 内抛出的异常只记日志，循环继续。
    """

    def __init__(
        self,
        name: str,
        run: Callable[[], Awaitable[None]],
        interval: Callable[[], float],
        initial_delay: float = 0.0,
        enabled: Callable[[], bool] = lambda: True,
    ) -> None:
        self._name = name
        self._run = run
        self._interval = interval
        self._initial_delay = initial_delay
        self._enabled = enabled
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()

    @property
    def name(self) -> str:
        return self._name

    @property
    def enabled(self) -> bool:
        return self._enabled()

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        """创建 asyncio 任务；已在运行时幂等返回。"""
        if self.running:
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._loop(), name=f"periodic:{self._name}")

    async def _loop(self) -> None:
        try:
            if self._initial_delay > 0:
                if await self._wait(self._initial_delay):
                    return
            while not self._stop_event.is_set():
                try:
                    await self._run()
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.error("%s tick failed: %s", self._name, e)
                # 间隔 <= 0 会让循环空转、日志暴涨，退回 1 秒
                interval = self._interval()
                if await self._wait(interval if interval > 0 else 1):
                    return
        except asyncio.CancelledError:
            pass

    async def _wait(self, timeout: float) -> bool:
        """最多等待 timeout 秒；收到停止信号返回 True。"""
        try:
            await asyncio.wait_for(self._stop_event.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    async def stop(self) -> None:
        """发出停止信号并等待任务退出；幂等。"""
        if self._task is None:
            return
        self._stop_event.set()
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None


class Scheduler:
    """持有一组 PeriodicTask，统一启停。"""

    def __init__(self, tasks: list[PeriodicTask]) -> None:
        self._tasks = tasks
        self._running = False

    @property
    def tasks(self) -> list[PeriodicTask]:
        return self._tasks

    @property
    def running(self) -> bool:
        return self._running

    def start_all(self) -> None:
        """启动所有当前 enabled() 为 True 的任务。"""
        for task in self._tasks:
            if task.enabled:
                task.start()
        self._running = True

    async def stop_all(self) -> None:
        await asyncio.gather(*(task.stop() for task in self._tasks))
        self._running = False
