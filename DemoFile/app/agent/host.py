"""装配与宿主：mini-harness 容器 + DeepSeek 提供方 + 存储工具 + 会话管理。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator

from mini_harness.agent import Agent, AgentsPlugin
from mini_harness.agent_loop import AgentLoopPlugin
from mini_harness.container import Context
from mini_harness.llm import LlmPlugin, LlmProvider
from mini_harness.session import Session, SessionEvent

from app.agent.provider import DeepSeekProvider
from app.agent.serialize import sse_frame
from app.agent.storage_tools import storage_tools_plugin
from app.core import context as app_context
from app.core.errors import BizException, ErrorCode

log = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "你是 MyFilesinNas（个人 NAS）的存储管理助手。"
    "你可以查询存储源与目录内容、新建文件夹、重命名条目。"
    "涉及文件事实的问题必须先调用工具查询真实数据，不要凭猜测回答；"
    "删除、移动、复制、上传目前没有工具，遇到这类请求如实告知。"
    "用简体中文回答，简洁直接；路径给完整形式。"
)

SSE_PING_SECONDS = 15.0


async def build_context(provider: LlmProvider) -> Context:
    ctx = Context()
    ctx.plugin(LlmPlugin([provider]))
    ctx.plugin(storage_tools_plugin())
    ctx.plugin(AgentsPlugin())
    ctx.plugin(AgentLoopPlugin())
    await ctx.ready()
    return ctx



class _OwnedAgent:
    """agent + 归属用户 + SSE 唤醒标记（一条流一个消费者共享同一个 tick 足够）。"""

    __slots__ = ("agent", "user_id", "tick")

    def __init__(self, agent: Agent, user_id: int) -> None:
        self.agent = agent
        self.user_id = user_id
        self.tick = asyncio.Event()

# 宿主类 常驻的管理器 由lifespan控制
# 目前会话全部内存存储
class AgentHost:
    """常驻宿主：后端嵌入形态的会话管理入口。

    - start()/stop() 由 main.py 的 lifespan 调用；缺少 DEEPSEEK_API_KEY 时
      start() 记为未启用（endpoints 返回明确错误），不影响站点启动。
    - 会话是纯内存的（mini-harness Session 无持久化），重启后全部丢失，
      前端需要重新创建会话，属预期。
    """

    def __init__(self) -> None:
        self._ctx: Context | None = None
        self._provider_name: str | None = None
        self._model: str | None = None
        self._entries: dict[str, _OwnedAgent] = {}

    @property
    def enabled(self) -> bool:
        return self._ctx is not None

    # 初始化agent 装配harness
    async def start(self) -> None:
        if self._ctx is not None:
            return
        try:
            provider = DeepSeekProvider()
        except ValueError as exc:
            log.info("agent 未启用：%s", exc)
            return
        self._ctx = await build_context(provider)
        self._ctx.on("session/event", self._on_session_event)
        self._provider_name = provider.name
        self._model = provider.model
        log.info("agent 已启用：provider=%s, model=%s", provider.name, provider.model)

    async def stop(self) -> None:
        if self._ctx is None:
            return
        await self._ctx.dispose()
        self._ctx = None
        self._entries.clear()

    # -- 会话控制面 ------------------------------------------------------

    def create(self, user_id: int) -> Agent:
        """建会话。必须在运行中的事件循环里调用（driver 要 create_task）。

        显式 set_current_user_id：loop task 的快照身份以本参数为准，而非调用点的
        请求上下文，这是工具以会话属主身份执行的唯一保证点。
        """
        ctx = self._require_ctx()
        app_context.set_current_user_id(user_id)
        agent = ctx.agents.create(
            system_prompt=SYSTEM_PROMPT,
            provider=self._provider_name or "deepseek",
            model=self._model or "deepseek-chat",
        )
        self._entries[agent.id] = _OwnedAgent(agent, user_id)
        return agent

    def get_owned(self, agent_id: str, user_id: int) -> Agent:
        """取会话并校验归属；不存在或不是本人 → BIZ_NOT_FOUND（不泄露他人会话存在性）。"""
        entry = self._entries.get(agent_id)
        if entry is None or entry.user_id != user_id:
            raise BizException(ErrorCode.BIZ_NOT_FOUND, "agent 会话不存在")
        return entry.agent

    def list_owned(self, user_id: int) -> list[Agent]:
        return [e.agent for e in self._entries.values() if e.user_id == user_id]

    async def dispose(self, agent_id: str, user_id: int) -> None:
        agent = self.get_owned(agent_id, user_id)
        assert self._ctx is not None
        await self._ctx.agents.dispose(agent)
        self._entries.pop(agent_id, None)

    # -- SSE 事件流 ------------------------------------------------------

    def _on_session_event(self, session: Session, event: SessionEvent) -> None:
        del event
        entry = self._entries.get(session.id)
        if entry is not None:
            entry.tick.set()

    async def stream(self, agent_id: str, user_id: int, since: int) -> AsyncIterator[str]:
        """先重放 since 之后的历史事件，再跟随新事件；空闲 15s 发一次注释保活。

        since 语义 = 已收到的最后 seq（SSE Last-Event-ID 的对齐方式，排他）：
        重放从 seq since+1 开始；since=-1（默认）从头重放。session 的 seq 由
        mini-harness 定为 0 基，若这里用包含式（index=since），默认 0 会吞掉 seq 0。

        消费者（HTTP 层）在开始前已校验过归属 —— 这里再取一次拿 entry；
        客户端断开时生成器被取消，无需清理（tick 是共享的，不属于单个连接）。
        """
        entry = self._entries.get(agent_id)
        if entry is None or entry.user_id != user_id:
            raise BizException(ErrorCode.BIZ_NOT_FOUND, "agent 会话不存在")
        agent = entry.agent
        index = max(since + 1, 0)
        while True:
            events = agent.session.events
            while index < len(events):
                yield sse_frame(events[index])
                index += 1
            entry.tick.clear()
            if index < len(agent.session.events):
                continue  # clear 前已有新事件落地，立即再次排空，避免丢失唤醒。
            try:
                await asyncio.wait_for(entry.tick.wait(), timeout=SSE_PING_SECONDS)
            except asyncio.TimeoutError:
                yield ": ping\n\n"

    def _require_ctx(self) -> Context:
        if self._ctx is None:
            raise BizException(ErrorCode.SYSTEM_ERROR, "agent 未启用（后端未配置 DEEPSEEK_API_KEY）")
        return self._ctx


# 模块级单例：路由与 lifespan 共用（进程内唯一宿主）
agent_host = AgentHost()
