"""事件总线：emit / waterfall / serial 三种分发模式。

实现对齐 dsh（DeepSeek Harness）``vendor/cordis/src/events.ts`` 的三模式语义：

- ``emit``      观察式广播：不等待结果、不改变数据流。
- ``waterfall`` 环绕中间件：监听器签名 ``(*args, next)``，调用 ``await next()``
                委托下游并拿到其返回值；不调用 ``next()`` 直接返回则短路整条链，
                用于拦截决策（拒批、改写、重试）。
- ``serial``    按注册序依次 await，收集每个监听器的返回值；用于终结检查点。

与 dsh 的差异：dsh 的 emit 是同步广播；这里允许监听器是协程，协程被调度为
后台任务，``drain()`` 用于等待它们完成，保证测试与演示的确定性。

三种模式对应的用途：
    emit      → 只观察（日志、通知）
    waterfall → 拦截 / 改写 / 短路（守卫、重试决策）
    serial    → 终结检查点，收集所有意见（turn-stopping）
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
        # 同一事件按注册顺序调用；撤销时只摘自己，不影响其他监听器。
        self._listeners.setdefault(name, []).append(listener)

        def dispose() -> None:
            bucket = self._listeners.get(name)
            if bucket is not None and listener in bucket:
                bucket.remove(listener)

        return dispose

    def emit(self, name: str, *args: Any) -> None:
        """广播：依次调用监听器；协程返回值的监听器被调度为后台任务。"""
        # 观察者模式：调用方不等待结果，也管不了别人干什么（拦截请用 waterfall）。
        for listener in list(self._listeners.get(name, ())):
            result = listener(*args)
            if inspect.isawaitable(result):
                # 异步监听器不阻塞当前调用方；drain() 负责收尾并把异常重新抛出。
                task = asyncio.get_running_loop().create_task(result)
                self._pending.add(task)
                task.add_done_callback(self._pending.discard)

    async def drain(self) -> None:
        """等待所有由 emit 调度的异步监听器完成；监听器抛错会在此处重新抛出。"""
        # 循环执行: 而不是 gather 一次就结束：监听器执行期间可能又 emit 出新的后台任务。
        while self._pending:
            results = await asyncio.gather(*list(self._pending), return_exceptions=True)
            for result in results:
                # 捕获执行错误
                if isinstance(result, BaseException):
                    raise result

    async def serial(self, name: str, *args: Any) -> list[Any]:
        """按注册序依次 await，返回每个监听器的返回值列表。"""
        # 终结检查点：所有监听器结果表态，调用方拿到完整结果列表
        results: list[Any] = []
        for listener in list(self._listeners.get(name, ())):
            result = listener(*args)
            if inspect.isawaitable(result):
                # await串行所有任务
                result = await result
            results.append(result)
        return results

    async def waterfall(self, name: str, *args: Any, default: Listener | None = None) -> Any:
        """链式委托分发：见模块 docstring 的语义说明。链尾调用 ``default(*args)``。"""
        # 瀑布链 = 递归的洋葱模型：listener(*inner, next_) 调了 next_ 才进入下一层；
        # 不调 next_ 直接 return 就是短路——后续监听器和 default 都不会执行。
        # 例：guard_plugin 命中路径穿越时直接 return PreToolDeny，工具执行被整段跳过。

        # 取出事件名对应全部监听器列表
        listeners = list(self._listeners.get(name, ()))

        async def call(index: int, *inner: Any) -> Any:
            if index >= len(listeners):
                # 递归到达链尾：落到默认实现
                if default is None:
                    return None
                result = default(*inner)
                return await result if inspect.isawaitable(result) else result
            # 取到本层监听器
            listener = listeners[index]

            # 交给listener的手动触发下一层
            async def next_(*forwarded: Any) -> Any:
                # 不传参 → 沿用当前参数（与 dsh/JS 的 next() 语义一致）；传参则替换。
                return await call(index + 1, *(forwarded if forwarded else inner))

            # 执行listener & 传入next
            result = listener(*inner, next_)
            # await调用保证外层等待内层
            return await result if inspect.isawaitable(result) else result
        # 启动
        return await call(0, *args)
