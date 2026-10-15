"""事件总线与插件容器行为测试。"""

from __future__ import annotations

import asyncio

from conftest import run_async
from mini_harness.container import Context
from mini_harness.events import Emitter


# -- waterfall ------------------------------------------------------------


@run_async
async def test_waterfall_delegates_and_unwinds_values() -> None:
    emitter = Emitter()
    trace: list[str] = []

    async def outer(x: int, next):
        trace.append("outer-in")
        result = await next()
        trace.append("outer-out")
        return result + 1

    async def inner(x: int, next):
        trace.append("inner-in")
        result = await next()
        trace.append("inner-out")
        return result + 10

    emitter.register("evt", outer)
    emitter.register("evt", inner)

    result = await emitter.waterfall("evt", 0, default=lambda x: x)

    assert result == 11  # inner(+10) 先包住 default，outer(+1) 再包住 inner
    assert trace == ["outer-in", "inner-in", "inner-out", "outer-out"]


@run_async
async def test_waterfall_short_circuit() -> None:
    emitter = Emitter()
    called: list[str] = []

    async def blocker(x: int, next):
        called.append("blocker")
        return x * 100  # 不调 next → 短路

    async def never(x: int, next):
        called.append("never")
        return await next()

    emitter.register("evt", blocker)
    emitter.register("evt", never)

    result = await emitter.waterfall("evt", 7, default=lambda x: x + 1)

    assert result == 700
    assert called == ["blocker"]  # 下游与 default 都未执行


@run_async
async def test_waterfall_listener_can_rewrite_forwarded_args() -> None:
    emitter = Emitter()

    async def rewriter(x: int, next):
        return await next(x + 5)

    emitter.register("evt", rewriter)

    assert await emitter.waterfall("evt", 1, default=lambda x: x * 2) == 12


# -- serial / emit --------------------------------------------------------


@run_async
async def test_serial_preserves_order_and_collects_results() -> None:
    emitter = Emitter()
    trace: list[int] = []

    def first(x: int) -> int:
        trace.append(1)
        return x + 1

    async def second(x: int) -> int:
        await asyncio.sleep(0)
        trace.append(2)
        return x + 2

    emitter.register("evt", first)
    emitter.register("evt", second)

    results = await emitter.serial("evt", 10)

    assert trace == [1, 2]
    assert results == [11, 12]


@run_async
async def test_emit_calls_sync_listeners_immediately_and_drains_async() -> None:
    emitter = Emitter()
    seen: list[str] = []

    emitter.register("evt", lambda x: seen.append(f"sync:{x}"))

    async def slow(x: str) -> None:
        await asyncio.sleep(0)
        seen.append(f"async:{x}")

    emitter.register("evt", slow)

    emitter.emit("evt", "a")
    assert "sync:a" in seen  # 同步监听器立即执行

    await emitter.drain()
    assert "async:a" in seen  # 异步监听器被 drain 等待


@run_async
async def test_disposer_removes_listener() -> None:
    emitter = Emitter()
    seen: list[int] = []
    dispose = emitter.register("evt", lambda x: seen.append(x))

    emitter.emit("evt", 1)
    dispose()
    emitter.emit("evt", 2)

    assert seen == [1]


# -- 容器：服务、inject、作用域 -------------------------------------------


@run_async
async def test_service_provide_and_attribute_proxy() -> None:
    ctx = Context()
    ctx.provide("greeter", "hello")

    assert ctx.greeter == "hello"
    assert ctx.get("greeter") == "hello"
    assert ctx.get("missing") is None

    try:
        ctx.missing
    except AttributeError:
        pass
    else:
        raise AssertionError("missing service should raise AttributeError")


@run_async
async def test_plugin_waits_for_injected_service() -> None:
    ctx = Context()
    events: list[str] = []

    class LatePlugin:
        name = "late"
        inject = ("greeter",)

        def apply(self, plugin_ctx: Context) -> None:
            events.append(f"activated:{plugin_ctx.greeter}")

    handle = ctx.plugin(LatePlugin())
    await ctx.ready()
    assert events == []  # 依赖缺失 → 挂起

    ctx.provide("greeter", "hi")
    await handle.ready()
    assert events == ["activated:hi"]


@run_async
async def test_plugin_effect_scope_disposed_on_unmount() -> None:
    ctx = Context()
    seen: list[str] = []

    def watcher(plugin_ctx: Context) -> None:
        plugin_ctx.on("evt", lambda: seen.append("plugin"))
        plugin_ctx.provide("from_plugin", 42)

    handle = ctx.plugin(watcher)
    await handle.ready()
    ctx.emit("evt")
    assert seen == ["plugin"]
    assert ctx.from_plugin == 42

    await handle.dispose()
    ctx.emit("evt")
    assert seen == ["plugin"]  # 监听器随插件卸载撤销
    assert ctx.get("from-plugin") is None  # 服务也随卸载移除


@run_async
async def test_dispose_runs_effects_lifo_and_is_idempotent() -> None:
    ctx = Context()
    order: list[int] = []
    ctx.effect(lambda: order.append(1))
    ctx.effect(lambda: order.append(2))

    await ctx.dispose()
    await ctx.dispose()

    assert order == [2, 1]
