"""Context插件容器 用于服务注册 / inject等待 / effect撤销
    实现插件相互依赖但是加载顺序不固定
    ## 简化放弃scope过滤分发: 使用扁平化共享总线和前缀命名实现

实现语义对齐 dsh 的 Cordis 容器（docs/cordis-primer.zh.md）：

- Context 是服务容器：服务占稳定键（ctx.llm / ctx.tools / ctx.agents）。
- 插件声明 inject 依赖；依赖未齐时挂起，注册新服务时自动激活就绪的挂起插件。
- 一切注册都是可逆副作用：effect() 记录 disposer，插件卸载/容器 dispose 时按 LIFO 撤销。
- 子 Context 是插件的作用域：插件在子 ctx 上的注册（服务、监听器）随卸载一并撤销。

未实现的能力（与 dsh 的边界）：

- scope 过滤分发：dsh 每次分发时读取 Context.filter，配合 isolate() 只通知某个作用域
  的监听器。这里只有一条全局总线，需要区分时由监听器从事件参数（session/agent）判断。
- 依赖反注册的级联卸载：dsh 的 Fiber 追踪 inject 的实现者，服务消失时自动卸载依赖
  它的插件。这里的服务只在挂载时 provide、容器整体 dispose 时撤销，运行期不存在
  服务消失，因此不需要反向依赖图。
- Loader/HMR：dsh 用配置驱动装配并支持热更新。这里由代码显式 ctx.plugin() 装配，
  修改插件后重启进程。
- 并行事件模式：dsh 的 parallel 等待全部监听器并聚合 AggregateError。这里的 emit
  已把协程监听器调度为后台任务，drain() 提供确定性汇合点，现有场景无需聚合语义。

容器只保留 agent loop 所需的最小生命周期语义；多 agent 作用域隔离、运行期热插拔、
配置化装配都需要在此扩展。
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
        self.ctx: Context | None = None            # 激活后指向该插件的子作用域
        self.error: BaseException | None = None    # apply 抛错时暂存，ready() 时重抛
        self._ready = asyncio.Event()              # 激活流程结束时 set

    async def ready(self) -> None:
        await self._ready.wait()
        if self.error is not None:
            raise self.error

    async def dispose(self) -> None:
        if self.ctx is not None:
            await self.ctx.dispose()


class _ParkedPlugin:
    """尚未激活的插件：依赖未齐时留在 _parked 队列，等 provide() 补齐后自动重试。"""

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
        self._effects: list[Disposer] = []   # 本作用域的撤销栈（LIFO）
        self._disposed = False
        if parent is None:
            # 根 Context 持有全局状态, 实现数据区物理共享的插件通信
            self._services: dict[str, Any] = {}
            self._emitter = Emitter()
            self._parked: list[_ParkedPlugin] = []
            self._activations: set[asyncio.Task[None]] = set()
            self._children: list[Context] = []
        else:
            # 子 Context 将内容登记到根，卸载时由根 Context 统一撤销
            parent._root._children.append(self)

    # -- 服务 ------------------------------------------------------------

    def provide(self, name: str, service: Any) -> Disposer:
        """注册一个服务到稳定键；返回撤销注册的 disposer（同时记入本 ctx 的副作用栈）。"""
        if name in self._root._services:
            raise RuntimeError(f"service already provided: {name!r}")
        self._root._services[name] = service

        # 不del 防止重复调用报错
        def dispose() -> None:
            self._root._services.pop(name, None)

        # 容器内记录每个服务的撤销事务 
        self.effect(dispose)
        # 新服务可能补齐挂起插件的 inject，立即重试激活；插件挂载顺序因此无关。
        self._root._activate_parked()
        # 交给调用方一个撤销句柄 提前撤销允许
        return dispose

    def get(self, name: str) -> Any | None:
        """安全读取服务；不存在时返回 None（对照 dsh 的 ``ctx.get(name)``）。"""
        return self._root._services.get(name)

    def __getattr__(self, name: str) -> Any:
        # 仅处理常规属性查找失败的情况；下划线开头直接拒绝，避免误触 dunder 协议。
        # 服务表挂在根上，任意子 Context 都能读到全局服务；未注册时显式报错。
        if name.startswith("_"):
            raise AttributeError(name)
        root = self.__dict__.get("_root")
        if root is not None and name in root._services:
            return root._services[name]
        raise AttributeError(f"service {name!r} is not registered")

    # -- 副作用 ----------------------------------------------------------

    def effect(self, dispose: Disposer) -> Disposer:
        """把一个 disposer 记入本 ctx 的副作用栈，容器 dispose 时按 LIFO 撤销。"""
        # on / provide / registry.register 的撤销函数最终都汇总到这里。
        self._effects.append(dispose)
        return dispose

    async def dispose(self) -> None:
        """卸载：先撤销所有子作用域（插件），再按 LIFO 执行自身副作用栈。幂等。"""
        if self._disposed:
            return
        self._disposed = True
        # 先递归卸载子 Context（插件作用域），再撤销本作用域的注册。
        for child in list(self._root._children):
            if child._parent is self:
                await child.dispose()
        # LIFO 撤销：后注册的先撤销, 先撤销无依赖
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
        """注册事件监听器；撤销注册随本 ctx 的副作用栈"""
        # 监听器挂在根 Emitter 上（共享总线），disposer 归属本插件作用域：
        # 插件卸载时自动摘除，避免留下指向已卸载对象的回调。
        return self.effect(self._root._emitter.register(name, listener))

    # 四种分法模式
    # 同步遍历
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
        必须在运行中的事件循环里调用。
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError as exc:
            raise RuntimeError(
                "mount plugins from a running event loop (call ctx.plugin() inside async code)"
            ) from exc
        handle = PluginHandle(_plugin_name(plugin))
        # 先入队再尝试激活；依赖不齐时留在队列，由后续 provide() 触发重试。
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
        # 扫描挂起队列：依赖齐的取出并异步激活，未齐的保留。provide() 与 plugin() 均会触发。
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
        # 每个插件获得独立子 Context：apply 里的 provide / on / effect 归属该作用域，
        # 卸载时只撤销插件自己的注册。
        child = Context(parent=parked.mount_ctx)
        parked.handle.ctx = child
        try:
            result = _apply(parked.plugin, child)
            if inspect.isawaitable(result):
                result = await result
            if callable(result):
                child.effect(result)  # 兼容 apply() 直接 return disposer 的写法
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
