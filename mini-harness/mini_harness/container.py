"""插件容器：Context、服务注册、inject 等待、effect/disposer、插件挂载。

直译自 dsh 的 Cordis 容器语义（``docs/cordis-primer.zh.md``）：

- Context 是服务容器：服务占稳定键（``ctx.llm`` / ``ctx.tools`` / ``ctx.agents``）。
- 插件声明 ``inject`` 依赖；依赖未齐时挂起，注册新服务时自动激活就绪的挂起插件。
- 一切注册都是可逆副作用：``effect()`` 记录 disposer，插件卸载/容器 dispose 时
  按 LIFO 撤销。
- 子 Context 是插件的作用域：插件在子 ctx 上的注册（服务、监听器）随卸载一并撤销。

与 dsh 的差异：砍掉 scope 过滤分发、依赖反注册的级联卸载、Loader/HMR/并行事件模式。
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable
from typing import Any

from mini_harness.events import Disposer, Emitter, Listener


class PluginHandle:
    """挂载句柄：``await ready()`` 等待激活完成；``await dispose()`` 卸载插件。"""

    def __init__(self, description: str) -> None:
        self.description = description
        self.ctx: Context | None = None
        self.error: BaseException | None = None
        self._ready = asyncio.Event()

    async def ready(self) -> None:
        await self._ready.wait()
        if self.error is not None:
            raise self.error

    async def dispose(self) -> None:
        if self.ctx is not None:
            await self.ctx.dispose()


class _ParkedPlugin:
    def __init__(self, mount_ctx: Context, plugin: Any, handle: PluginHandle) -> None:
        self.mount_ctx = mount_ctx
        self.plugin = plugin
        self.handle = handle


class Context:
    """服务容器 + 事件入口 + 插件作用域。

    根 Context（``Context()``）持有全局服务表与事件总线；每个插件在激活时获得
    一个子 Context，其上的 ``effect`` / ``on`` / ``provide`` 都随插件卸载撤销。
    """

    def __init__(self, parent: Context | None = None) -> None:
        self._parent = parent
        self._root = parent._root if parent is not None else self
        self._effects: list[Disposer] = []
        self._disposed = False
        if parent is None:
            self._services: dict[str, Any] = {}
            self._emitter = Emitter()
            self._parked: list[_ParkedPlugin] = []
            self._activations: set[asyncio.Task[None]] = set()
            self._children: list[Context] = []
        else:
            parent._root._children.append(self)

    # -- 服务 ------------------------------------------------------------

    def provide(self, name: str, service: Any) -> Disposer:
        """注册一个服务到稳定键；返回撤销注册的 disposer（同时记入本 ctx 的副作用栈）。"""
        if name in self._root._services:
            raise RuntimeError(f"service already provided: {name!r}")
        self._root._services[name] = service

        def dispose() -> None:
            self._root._services.pop(name, None)

        self.effect(dispose)
        self._root._activate_parked()
        return dispose

    def get(self, name: str) -> Any | None:
        """安全读取服务；不存在时返回 None（对照 dsh 的 ``ctx.get(name)``）。"""
        return self._root._services.get(name)

    def __getattr__(self, name: str) -> Any:
        # __getattr__ 只在常规查找失败后被调用；_ 开头直接拒绝，避免 dunder 协议被误查。
        if name.startswith("_"):
            raise AttributeError(name)
        root = self.__dict__.get("_root")
        if root is not None and name in root._services:
            return root._services[name]
        raise AttributeError(f"service {name!r} is not registered")

    # -- 副作用 ----------------------------------------------------------

    def effect(self, dispose: Disposer) -> Disposer:
        """把一个 disposer 记入本 ctx 的副作用栈，容器 dispose 时按 LIFO 撤销。"""
        self._effects.append(dispose)
        return dispose

    async def dispose(self) -> None:
        """卸载：先撤销所有子作用域（插件），再按 LIFO 执行自身副作用栈。幂等。"""
        if self._disposed:
            return
        self._disposed = True
        for child in list(self._root._children):
            if child._parent is self:
                await child.dispose()
        for dispose in reversed(self._effects):
            result = dispose()
            if inspect.isawaitable(result):
                await result
        self._effects.clear()
        parent = self._parent
        if parent is not None and self in parent._root._children:
            parent._root._children.remove(self)

    # -- 事件 ------------------------------------------------------------

    def on(self, name: str, listener: Listener) -> Disposer:
        """注册事件监听器；撤销注册随本 ctx 的副作用栈（对照 dsh 的 ``ctx.on``）。"""
        return self.effect(self._root._emitter.register(name, listener))

    def emit(self, name: str, *args: Any) -> None:
        self._root._emitter.emit(name, *args)

    async def serial(self, name: str, *args: Any) -> list[Any]:
        return await self._root._emitter.serial(name, *args)

    async def waterfall(self, name: str, *args: Any, default: Listener | None = None) -> Any:
        return await self._root._emitter.waterfall(name, *args, default=default)

    async def drain(self) -> None:
        """等待 emit 调度的异步监听器完成。"""
        await self._root._emitter.drain()

    # -- 插件 ------------------------------------------------------------

    def plugin(self, plugin: Any) -> PluginHandle:
        """挂载插件（函数或带 ``apply`` 的对象），返回挂载句柄。

        依赖（``inject``）满足时立即调度激活；否则挂起，等 ``provide`` 补齐依赖后自动激活。
        必须在运行中的事件循环里调用（测试/demo 均在 async 上下文中）。
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError as exc:
            raise RuntimeError(
                "mount plugins from a running event loop (call ctx.plugin() inside async code)"
            ) from exc
        handle = PluginHandle(_plugin_name(plugin))
        self._root._parked.append(_ParkedPlugin(self, plugin, handle))
        self._root._activate_parked()
        return handle

    async def ready(self) -> None:
        """等待所有已调度的插件激活完成。依赖未满足而挂起的插件不在此列。

        激活失败（apply 抛错）会在此处重新抛出。
        """
        while True:
            tasks = list(self._root._activations)
            if not tasks:
                break
            await asyncio.gather(*tasks)

    # -- 内部 ------------------------------------------------------------

    def _activate_parked(self) -> None:
        still: list[_ParkedPlugin] = []
        for parked in self._root._parked:
            if _deps_ready(parked.plugin, self._root._services):
                task = asyncio.get_running_loop().create_task(self._activate(parked))
                self._root._activations.add(task)
                task.add_done_callback(self._root._activations.discard)
            else:
                still.append(parked)
        self._root._parked = still

    async def _activate(self, parked: _ParkedPlugin) -> None:
        child = Context(parent=parked.mount_ctx)
        parked.handle.ctx = child
        try:
            result = _apply(parked.plugin, child)
            if inspect.isawaitable(result):
                result = await result
            if callable(result):
                child.effect(result)
        except BaseException as exc:
            parked.handle.error = exc
            await child.dispose()
        finally:
            parked.handle._ready.set()


def _apply(plugin: Any, ctx: Context) -> Any:
    apply = getattr(plugin, "apply", None)
    if apply is not None and callable(apply):
        return apply(ctx)
    if callable(plugin):
        return plugin(ctx)
    raise TypeError(f"not a plugin (needs apply() or be callable): {plugin!r}")


def _deps(plugin: Any) -> tuple[str, ...]:
    return tuple(getattr(plugin, "inject", ()))


def _deps_ready(plugin: Any, services: dict[str, Any]) -> bool:
    return all(name in services for name in _deps(plugin))


def _plugin_name(plugin: Any) -> str:
    return getattr(plugin, "name", None) or getattr(plugin, "__name__", None) or repr(plugin)
