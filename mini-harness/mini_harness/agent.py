"""Agent 句柄与 inbox：对外控制面与驱动器装配。

直译自 dsh ``packages/core/agent``（docs/subsystems/agent-lifecycle.zh.md、
``packages/core/agent/src/runtime-types.ts``）：

- ``Agent`` 是对外句柄：``followup``（排入下一轮）／``steer``（排入下一步并唤醒）／
  ``inject``（排入下一步但不唤醒）／``cancel``／``when_idle``；
- inbox 两条队列：next_turn（轮次边界，每轮只领取一条）与 next_step（步边界，
  全部领取）；loop 是唯一消费者，句柄只负责生产；
- ``ctx.agents`` 注册表负责装配：建 Session、把每次 append 广播到
  ``session/event``、调用 driver 启动常驻 loop task；容器卸载时停掉全部 agent。

与 dsh 的差异：砍掉 scope/initiator、subagent、恢复与细粒度 AgentStatus。

阅读提示：本文件是「控制面」，agent_loop.py 是「数据面」。Agent 句柄只负责
往 inbox 里放消息；AgentLoop 是 inbox 的唯一消费者。AgentRegistry.create()
是关键装配点：建 Session → 把 append 广播接到 ctx.emit("session/event")
→ 启动常驻 loop task。cancel() 只中止当前工作，不会杀死 loop。
"""

from __future__ import annotations

import asyncio
import uuid
from collections import deque
from dataclasses import dataclass
from typing import Literal, Protocol

from mini_harness.container import Context
from mini_harness.events import Disposer
from mini_harness.session import Session


@dataclass(frozen=True)
class InboxMessage:
    id: str
    content: str
    # 生产者标识会写进 user/message 日志（UserMessageData.source），便于观察来源
    source: str  # user / steer / inject / 插件名

    @staticmethod
    def text(source: str, content: str) -> "InboxMessage":
        return InboxMessage(id=uuid.uuid4().hex[:8], content=content, source=source)


class Inbox:
    """两条队列 + 唤醒事件；句柄与 loop 之间唯一的交互点。"""

    def __init__(self) -> None:
        self.next_turn: deque[InboxMessage] = deque()  # 轮次边界领取：每轮只取一条
        self.next_step: deque[InboxMessage] = deque()  # 步边界领取：step 结束后全部取走
        self._wake = asyncio.Event()  # 只负责唤醒 loop task，不代表队列有货（可能有 inject）

    @property
    def pending(self) -> bool:
        return bool(self.next_turn or self.next_step)

    def enqueue_turn(self, message: InboxMessage, *, wake: bool = True) -> None:
        self.next_turn.append(message)
        if wake:
            self._wake.set()

    def enqueue_step(self, message: InboxMessage, *, wake: bool = True) -> None:
        self.next_step.append(message)
        if wake:
            self._wake.set()

    async def wait(self) -> None:
        """等待被唤醒；醒来即消费唤醒标记。"""
        # 醒来立刻清标记：之后排入的消息会重新 set，不会丢唤醒；
        # 若被 clear() 清空队列导致空转，_run() 会检查 pending 后继续睡。
        await self._wake.wait()
        self._wake.clear()

    def claim_for_turn(self) -> list[InboxMessage]:
        """轮次边界领取：全部 next_step + 一条 next_turn。"""
        # 先拿 next_step（steer/inject 属于当前注意力范围），再取一条 followup 开新轮。
        claimed = list(self.next_step)
        self.next_step.clear()
        if self.next_turn:
            claimed.append(self.next_turn.popleft())
        return claimed

    def claim_for_step(self) -> list[InboxMessage]:
        """步边界领取：只取 next_step（next_turn 留给下一轮）。"""
        # 这就是 followup 与 steer 的核心区别：steer 能在当前 turn 的下一步插队。
        claimed = list(self.next_step)
        self.next_step.clear()
        return claimed

    def clear(self) -> None:
        self.next_turn.clear()
        self.next_step.clear()
        self._wake.clear()


class Agent:
    """对外句柄。loop 由驱动器持有；驾驶相关状态（_idle/_task/_closed）仅限驱动层触碰。"""

    def __init__(
        self,
        agent_id: str,
        *,
        session: Session,
        provider: str,
        model: str,
        system_prompt: str | None = None,
    ) -> None:
        self.id = agent_id
        self.session = session
        self.provider = provider
        self.model = model
        self.system_prompt = system_prompt
        self.status: Literal["idle", "running"] = "idle"
        self.last_error: BaseException | None = None
        self.inbox = Inbox()
        self._task: asyncio.Task[None] | None = None
        self._idle = asyncio.Event()
        self._idle.set()
        self._closed = False
        self._cancel_keep_inbox = False

    @property
    def closed(self) -> bool:
        return self._closed

    # -- 控制面 ----------------------------------------------------------

    def followup(self, content: str, *, source: str = "user") -> InboxMessage:
        """排入下一轮并唤醒 loop。"""
        # 语义：等当前 turn 彻底结束后，下一轮才处理（排队新任务）。
        message = self._enqueue(content, source, step=False)
        return message

    def steer(self, content: str, *, source: str = "steer") -> InboxMessage:
        """排入下一步并唤醒 loop；loop 空闲时该消息开启新轮次。"""
        # 语义：打断式插队——当前 step 结束后立刻进入下一 step 处理它。
        return self._enqueue(content, source, step=True)

    def inject(self, content: str, *, source: str = "inject") -> InboxMessage:
        """排入下一步但不唤醒；由下一次唤醒顺带领取。"""
        # 语义：静默注入上下文，不主动把 loop 从睡眠中叫醒。
        message = self._enqueue(content, source, step=True, wake=False)
        return message

    def cancel(self, *, keep_inbox: bool = False) -> None:
        """中止当前工作（loop 不终止）；默认清空 inbox。"""
        # 实现是 cancel 掉 loop task：agent_loop._run() 捕获 CancelledError 后
        # 做日志收口并继续 while 循环，所以 loop 本身不会退出。
        task = self._task
        if task is None or task.done():
            if not keep_inbox:
                self.inbox.clear()
            return
        self._cancel_keep_inbox = keep_inbox
        task.cancel()

    async def when_idle(self) -> None:
        """等到没有进行中的工作且 inbox 无待领取消息（agent 已关闭则立即返回）。"""
        # demo/tests 的同步点：idle 事件只表示「loop 睡了」，还要确认 inbox 真的空了，
        # 否则可能在两轮之间的空隙提前返回。sleep(0) 让出一拍，避免忙等饿死 loop。
        while True:
            if self._closed or (self._task is not None and self._task.done()):
                return
            if self.status == "idle" and not self.inbox.pending:
                return
            await self._idle.wait()
            await asyncio.sleep(0)

    # -- 驱动层（AgentLoop 专用） ----------------------------------------

    def mark_idle(self) -> None:
        self.status = "idle"
        self._idle.set()

    def mark_running(self) -> None:
        self._idle.clear()
        self.status = "running"

    def take_cancel_keep_inbox(self) -> bool:
        """取走并复位 cancel() 留下的 keep_inbox 标记。"""
        keep = self._cancel_keep_inbox
        self._cancel_keep_inbox = False
        return keep

    def _enqueue(self, content: str, source: str, *, step: bool, wake: bool = True) -> InboxMessage:
        # followup/steer/inject 的唯一分叉点：进哪条队列 + 是否唤醒 loop。
        if self._closed:
            raise RuntimeError(f"agent {self.id!r} is closed")
        message = InboxMessage.text(source, content)
        if step:
            self.inbox.enqueue_step(message, wake=wake)
        else:
            self.inbox.enqueue_turn(message, wake=wake)
        return message


class AgentDriver(Protocol):
    """驱动器协议：``start`` 接收 agent，返回常驻的 loop task。"""

    def start(self, agent: Agent) -> asyncio.Task[None]: ...


class AgentRegistry:
    """注册在 ``ctx.agents``：装配 agent 并管理其生命周期。"""

    def __init__(self, ctx: Context) -> None:
        self._ctx = ctx
        self._driver: AgentDriver | None = None
        self._agents: dict[str, Agent] = {}
        self._counter = 0

    def register_driver(self, driver: AgentDriver) -> Disposer:
        if self._driver is not None:
            raise RuntimeError("an agent driver is already registered")
        self._driver = driver

        def dispose() -> None:
            if self._driver is driver:
                self._driver = None

        return dispose

    def create(
        self,
        agent_id: str | None = None,
        *,
        provider: str = "mock",
        model: str = "mock",
        system_prompt: str | None = None,
    ) -> Agent:
        if self._driver is None:
            raise RuntimeError("no agent driver registered (mount AgentLoopPlugin first)")
        self._counter += 1
        aid = agent_id or f"agent-{self._counter}"
        if aid in self._agents:
            raise RuntimeError(f"agent already exists: {aid!r}")
        # 1) 每个 agent 一份仅追加的 Session 日志
        session = Session(id=aid)
        # 2) 把日志的每次 append 广播成全局 session/event（logging 等观察者监听）
        session.set_notify(lambda s, event: self._ctx.emit("session/event", s, event))
        agent = Agent(
            aid,
            session=session,
            provider=provider,
            model=model,
            system_prompt=system_prompt,
        )
        self._agents[aid] = agent
        # 3) 启动常驻 loop task：它独占消费 agent.inbox，直到 dispose/closed
        agent._task = self._driver.start(agent)
        return agent

    def get(self, agent_id: str) -> Agent | None:
        return self._agents.get(agent_id)

    def list(self) -> tuple[Agent, ...]:
        return tuple(self._agents.values())

    async def dispose(self, agent: Agent) -> None:
        """关闭一个 agent：停掉 loop task 并移出注册表。"""
        agent._closed = True
        task = agent._task
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._agents.pop(agent.id, None)

    async def dispose_all(self) -> None:
        for agent in self.list():
            await self.dispose(agent)


class AgentsPlugin:
    """提供 ``ctx.agents`` 服务；插件卸载时停掉全部 agent。"""

    name = "agents"

    def apply(self, ctx: Context) -> None:
        registry = AgentRegistry(ctx)
        ctx.provide("agents", registry)
        # 容器支持 await 异步 disposer：插件卸载时停掉所有 loop task。
        ctx.effect(lambda: registry.dispose_all())
