"""事件总线：emit / waterfall / serial 三种分发模式。

直译自 dsh（DeepSeek Harness）``vendor/cordis/src/events.ts`` 的三模式语义：

- ``emit``      观察式广播：不等待结果、不改变数据流。
- ``waterfall`` 环绕中间件：监听器签名 ``(*args, next)``，调用 ``await next()``
                委托下游并拿到其返回值；不调用 ``next()`` 直接返回 = 短路整条链，
                这是拦截决策事件（拒批、改写、重试）的设计意图。
- ``serial``    按注册序依次 await，收集每个监听器的返回值；用于终结检查点。

与 dsh 的差异：dsh 的 emit 是同步广播；mini 允许监听器是协程，协程会被调度为
后台任务，``drain()`` 用于等待它们完成（让测试与演示保持确定性）。
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable
from typing import Any

Disposer = Callable[[], None]
Listener = Callable[..., Any]


class Emitter:
    """按事件名维护监听器列表，提供三种分发模式。"""

    def __init__(self) -> None:
        self._listeners: dict[str, list[Listener]] = {}
        self._pending: set[asyncio.Task[Any]] = set()

    def register(self, name: str, listener: Listener) -> Disposer:
        """注册监听器，返回撤销注册的 disposer。"""
        self._listeners.setdefault(name, []).append(listener)

        def dispose() -> None:
            bucket = self._listeners.get(name)
            if bucket is not None and listener in bucket:
                bucket.remove(listener)

        return dispose

    def emit(self, name: str, *args: Any) -> None:
        """广播：依次调用监听器；协程返回值的监听器被调度为后台任务。"""
        for listener in list(self._listeners.get(name, ())):
            result = listener(*args)
            if inspect.isawaitable(result):
                task = asyncio.get_running_loop().create_task(result)
                self._pending.add(task)
                task.add_done_callback(self._pending.discard)

    async def drain(self) -> None:
        """等待所有由 emit 调度的异步监听器完成；监听器抛错会在此处重新抛出。"""
        while self._pending:
            results = await asyncio.gather(*list(self._pending), return_exceptions=True)
            for result in results:
                if isinstance(result, BaseException):
                    raise result

    async def serial(self, name: str, *args: Any) -> list[Any]:
        """按注册序依次 await，返回每个监听器的返回值列表。"""
        results: list[Any] = []
        for listener in list(self._listeners.get(name, ())):
            result = listener(*args)
            if inspect.isawaitable(result):
                result = await result
            results.append(result)
        return results

    async def waterfall(self, name: str, *args: Any, default: Listener | None = None) -> Any:
        """链式委托分发：见模块 docstring 的语义说明。链尾调用 ``default(*args)``。"""
        listeners = list(self._listeners.get(name, ()))

        async def call(index: int, *inner: Any) -> Any:
            if index >= len(listeners):
                if default is None:
                    return None
                result = default(*inner)
                return await result if inspect.isawaitable(result) else result
            listener = listeners[index]

            async def next_(*forwarded: Any) -> Any:
                # 不传参 → 沿用当前参数（与 dsh/JS 的 next() 语义一致）；传参则替换。
                return await call(index + 1, *(forwarded if forwarded else inner))

            result = listener(*inner, next_)
            return await result if inspect.isawaitable(result) else result

        return await call(0, *args)
