"""插件容器：Context、服务注册、inject 等待、effect/disposer、插件挂载。

直译自 dsh 的 Cordis 容器语义（``docs/cordis-primer.zh.md``）：

- Context 是服务容器：服务占稳定键（``ctx.llm`` / ``ctx.tools`` / ``ctx.agents``）。
- 插件声明 ``inject`` 依赖；依赖未齐时挂起，注册新服务时自动激活就绪的挂起插件。
- 一切注册都是可逆副作用：``effect()`` 记录 disposer，插件卸载/容器 dispose 时
  按 LIFO 撤销。
- 子 Context 是插件的作用域：插件在子 ctx 上的注册（服务、监听器）随卸载一并撤销。

与 dsh 的差异（均为有意裁剪，理由如下）：

- **scope 过滤分发**：dsh 的 Context 在每次事件分发时读取 ``Context.filter``，
  配合 ``isolate()`` 实现「只通知某个作用域的监听器」（多实例/嵌套作用域）。
  mini 只有一条全局总线：demo 里只有一个 agent，监听器需要区分时直接从事件参数
  （session/agent）里判断即可。真正的 scope 过滤要引入作用域树和逐次过滤，
  属于多实例平台能力，不是 agent loop 的核心。
- **依赖反注册的级联卸载**：dsh 的 Fiber 会追踪 inject 的实现者，服务消失时
  ``_refresh()`` 把 epoch 置为 INACTIVE 并自动卸载依赖它的插件（服务回来再重载）。
  mini 的服务只在挂载时 ``provide``、在容器整体 dispose 时撤销，正常使用中不存在
  「运行期服务消失」，因此不需要反向依赖图和级联卸载。
- **Loader/HMR**：dsh 有配置驱动的 Loader（cordis.yml、include、overlay）和热更新，
  面向长期运行的开发服务器。mini 用代码显式 ``ctx.plugin()`` 装配，改插件就重启；
  文件监听、模块图、状态保留都属于平台层，与理解 agent loop 无关。
- **并行事件模式**：dsh 的 ``parallel`` 等待全部监听器并聚合 AggregateError。
  mini 的 ``emit`` 已把协程监听器调度为后台任务，``drain()`` 提供确定性的汇合点，
  「扇出 + 等待」已覆盖；agent loop 没有任何地方需要全量等待 + 多错误聚合语义。

共同理由：本项目的目标是演示 agent loop 的七个核心机制，容器只保留这些机制需要的
最小生命周期语义；上述能力都会显著增加代码量和间接层，偏离「零依赖、可测、可读」。
裁剪带来的代价也明确：多 agent 作用域隔离、运行期热插拔服务、配置化装配需要自行
扩展——这正是 README「与 dsh 的差异」表的用途：标出学习边界。

阅读提示（装配起点）：``examples/demo.py`` 里的 ``ctx.plugin(X)`` 进入本文件 →
检查插件 ``inject`` 声明的服务是否已齐 → 就绪则建子 Context 并执行 ``X.apply(child)``。
tools / llm / agent 等模块的 Plugin 都在 apply 里 ``provide`` 服务或注册监听器，
由本文件的「服务表 + 副作用栈」统一管理生命周期。
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
            # 只有根 Context 持有全局状态：服务表、事件总线、待激活队列、子作用域表
            self._services: dict[str, Any] = {}
            self._emitter = Emitter()
            self._parked: list[_ParkedPlugin] = []
            self._activations: set[asyncio.Task[None]] = set()
            self._children: list[Context] = []
        else:
            # 子 Context（插件作用域）登记到根，卸载时由父级统一撤销
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
        # 关键联动：新服务可能正好补齐某个挂起插件的 inject，立刻重试激活。
        # 这就是 demo 里插件挂载顺序无关、AgentLoopPlugin 能「等」到 agents/tools/llm 的原因。
        self._root._activate_parked()
        return dispose

    def get(self, name: str) -> Any | None:
        """安全读取服务；不存在时返回 None（对照 dsh 的 ``ctx.get(name)``）。"""
        return self._root._services.get(name)

    def __getattr__(self, name: str) -> Any:
        # __getattr__ 只在常规查找失败后被调用；_ 开头直接拒绝，避免 dunder 协议被误查。
        # ctx.tools / ctx.llm / ctx.agents 这类属性式取服务的语法就靠这里：
        # 服务表挂在根上，所以任意子 Context 都能读到全局服务；找不到时显式报错。
        if name.startswith("_"):
            raise AttributeError(name)
        root = self.__dict__.get("_root")
        if root is not None and name in root._services:
            return root._services[name]
        raise AttributeError(f"service {name!r} is not registered")

    # -- 副作用 ----------------------------------------------------------

    def effect(self, dispose: Disposer) -> Disposer:
        """把一个 disposer 记入本 ctx 的副作用栈，容器 dispose 时按 LIFO 撤销。"""
        # 「注册即可逆」：on / provide / registry.register 最终都把撤销函数记到这里。
        self._effects.append(dispose)
        return dispose

    async def dispose(self) -> None:
        """卸载：先撤销所有子作用域（插件），再按 LIFO 执行自身副作用栈。幂等。"""
        if self._disposed:
            return
        self._disposed = True
        # 先递归卸载子 Context（插件作用域），插件自己的注册随之撤销。
        for child in list(self._root._children):
            if child._parent is self:
                await child.dispose()
        # LIFO 撤销：后注册的先撤销（例如先摘监听器，再关闭它依赖的服务）。
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
        # 监听器实际装在根 Emitter 上（所有插件共享总线），但 disposer 归本插件作用域：
        # 插件卸载 → 自动摘除监听器，不会留下指向已卸载对象的回调。
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
        # 先入队再尝试激活：依赖不齐就留在队列里，等下一次 provide() 触发重试。
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
        # 每次调用都把挂起队列扫一遍：依赖齐的取出并异步激活，仍未齐的留下。
        # provide() 与 plugin() 都会触发它，形成「依赖补齐 → 自动上岗」的机制。
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
        # 每个插件拿到一个子 Context：apply 里的 provide / on / effect 都归属这个作用域，
        # 卸载该插件时只撤销它自己的东西。
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
