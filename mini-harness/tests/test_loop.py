"""Agent loop 端到端测试：轮次/步序列、拦截点、重试、取消与并发调度。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterable
from typing import Any

import pytest

from conftest import run_async
from mini_harness.agent import Agent, AgentsPlugin, Inbox, InboxMessage
from mini_harness.agent_loop import AgentLoopPlugin, RequestErrorRetry
from mini_harness.container import Context
from mini_harness.llm import (
    GenerateOptions,
    LlmError,
    LlmPlugin,
    MockProvider,
    ScriptedResponse,
    StreamChunk,
    text_response,
    tool_call_response,
)
from mini_harness.messages import BlockStart, BlockEnd, Finish, TextDelta, message_text
from mini_harness.session import ToolResultMessage, derive_messages
from mini_harness.tools import ToolDefinition, ToolsPlugin


class ScriptProvider:
    """测试提供方：按 behavior 剧本演出。

    behavior 可以是：
    - ``ScriptedResponse``：照演；
    - ``("gate", text)``：先吐 text，再挂在 ``gate`` 上（等测试放行）；
    - ``("fail", code)``：抛 ``LlmError(code)``。
    """

    name = "mock"

    def __init__(self) -> None:
        self.gate = asyncio.Event()
        self.behaviors: list[Any] = []
        self.calls = 0
        self.hung = False

    def push(self, *behaviors: Any) -> None:
        self.behaviors.extend(behaviors)

    async def stream(self, options: GenerateOptions) -> AsyncIterator[StreamChunk]:
        self.calls += 1
        if not self.behaviors:
            raise LlmError("SCRIPT_EXHAUSTED", "no behavior left")
        behavior = self.behaviors.pop(0)
        if isinstance(behavior, ScriptedResponse):
            for chunk in behavior.chunks:
                await asyncio.sleep(0)
                yield chunk
            return
        if behavior[0] == "fail":
            raise LlmError(behavior[1], "scripted failure")
        yield BlockStart(0, "text")
        yield TextDelta(0, behavior[1])
        self.hung = True
        await self.gate.wait()
        self.hung = False
        yield BlockEnd(0)
        yield Finish("stop")


def _echo_tool(*, safe: bool = False) -> ToolDefinition:
    def execute(args: dict) -> str:
        return f"echo:{args.get('text', '')}"

    return ToolDefinition(
        name="echo",
        description="echo text back",
        parameters={"type": "object"},
        execute=execute,
        is_concurrency_safe=safe,
    )


async def _env(
    *,
    provider: Any | None = None,
    tools: Iterable[ToolDefinition] = (),
    system_prompt: str | None = None,
    max_parallel_tool_calls: int = 10,
) -> tuple[Context, Agent, Any]:
    ctx = Context()
    provider = provider if provider is not None else MockProvider()
    ctx.plugin(LlmPlugin([provider]))
    ctx.plugin(ToolsPlugin(tools))
    ctx.plugin(AgentsPlugin())
    ctx.plugin(AgentLoopPlugin(max_parallel_tool_calls=max_parallel_tool_calls))
    await ctx.ready()
    agent = ctx.agents.create(system_prompt=system_prompt)
    return ctx, agent, provider


async def _wait_for(predicate: Any, *, limit: int = 500) -> None:
    for _ in range(limit):
        if predicate():
            return
        await asyncio.sleep(0)
    raise AssertionError("condition not satisfied in time")


def _types(session: Any) -> list[str]:
    return [event.type for event in session.events]


def _texts(session: Any) -> list[str]:
    return [
        message_text(message)
        for message in derive_messages(session)
        if not isinstance(message, ToolResultMessage)
    ]


# -- 基本轮次 --------------------------------------------------------------


@run_async
async def test_single_text_turn_end_to_end() -> None:
    provider = MockProvider(script=[text_response("hello there")])
    ctx, agent, _ = await _env(provider=provider)
    try:
        agent.followup("hi")
        await agent.when_idle()

        assert _types(agent.session) == [
            "turn/start",
            "user/message",
            "step/start",
            "assistant/message",
            "step/end",
            "turn/end",
        ]
        assert _texts(agent.session) == ["hi", "hello there"]
        assert [event.data.status for event in agent.session.events_of("turn/end")] == ["completed"]
        assert agent.status == "idle"
        assert agent.last_error is None
        assert not agent.inbox.pending
    finally:
        await ctx.dispose()


@run_async
async def test_system_prompt_logged_once_across_turns() -> None:
    provider = MockProvider(script=[text_response("one"), text_response("two")])
    ctx, agent, _ = await _env(provider=provider, system_prompt="you are terse")
    try:
        agent.followup("first")
        await agent.when_idle()
        agent.followup("second")
        await agent.when_idle()

        assert len(agent.session.events_of("system/message")) == 1
        messages = derive_messages(agent.session)
        assert [message.role for message in messages] == [
            "system",
            "user",
            "assistant",
            "user",
            "assistant",
        ]
        assert message_text(messages[0]) == "you are terse"
    finally:
        await ctx.dispose()


@run_async
async def test_session_events_broadcast_via_ctx() -> None:
    provider = MockProvider(script=[text_response("yo")])
    ctx, agent, _ = await _env(provider=provider)
    seen: list[tuple[str, int]] = []
    ctx.on("session/event", lambda session, event: seen.append((event.type, event.seq)))
    try:
        agent.followup("hi")
        await agent.when_idle()

        assert seen == [(event.type, event.seq) for event in agent.session.events]
    finally:
        await ctx.dispose()


# -- 工具回合 --------------------------------------------------------------


@run_async
async def test_tool_round_trip_events_and_history() -> None:
    provider = MockProvider(
        script=[
            tool_call_response(("echo", {"text": "world"})),
            text_response("done"),
        ]
    )
    ctx, agent, _ = await _env(provider=provider, tools=[_echo_tool()])
    try:
        agent.followup("read it")
        await agent.when_idle()

        assert _types(agent.session) == [
            "turn/start",
            "user/message",
            "step/start",
            "assistant/message",
            "tool/call",
            "tool/result",
            "step/end",
            "step/start",
            "assistant/message",
            "step/end",
            "turn/end",
        ]
        call = agent.session.events_of("tool/call")[0].data
        assert call.name == "echo"
        result = agent.session.events_of("tool/result")[0].data.message
        assert result.content == "echo:world"
        assert result.is_error is False

        messages = derive_messages(agent.session)
        assert [getattr(message, "role", "tool") for message in messages] == [
            "user",
            "assistant",
            "tool",
            "assistant",
        ]
        assert messages[2] == result
    finally:
        await ctx.dispose()


@run_async
async def test_guard_denial_reaches_model_history() -> None:
    provider = MockProvider(
        script=[
            tool_call_response(("echo", {"text": "x"})),
            text_response("understood"),
        ]
    )
    ctx, agent, _ = await _env(provider=provider, tools=[_echo_tool()])

    async def guard(view: Any, next: Any) -> Any:
        from mini_harness.tools import PreToolDeny

        if view.name == "echo":
            return PreToolDeny(reason="echo is banned")
        return await next()

    ctx.on("tools/pre-execute", guard)
    try:
        agent.followup("go")
        await agent.when_idle()

        result = agent.session.events_of("tool/result")[0].data.message
        assert result.is_error is True
        assert result.content == "Error: echo is banned"
        assert result in derive_messages(agent.session)
        assert len(agent.session.events_of("assistant/message")) == 2  # 第二轮请求基于错误收尾
        assert _texts(agent.session)[-1] == "understood"
    finally:
        await ctx.dispose()


@run_async
async def test_unknown_tool_result_is_error() -> None:
    provider = MockProvider(
        script=[tool_call_response(("nope", {})), text_response("ok")]
    )
    ctx, agent, _ = await _env(provider=provider)
    try:
        agent.followup("go")
        await agent.when_idle()

        result = agent.session.events_of("tool/result")[0].data.message
        assert result.is_error is True
        assert result.content == "Error: unknown tool: nope"
    finally:
        await ctx.dispose()


# -- 请求错误与重试 --------------------------------------------------------


@run_async
async def test_request_error_retry_within_same_step() -> None:
    provider = ScriptProvider()
    provider.push(("fail", "BOOM"), text_response("recovered"))
    ctx, agent, _ = await _env(provider=provider)
    attempts: list[str] = []

    async def retry_once(agent_: Agent, exc: LlmError, next: Any) -> Any:
        attempts.append(exc.code)
        if len(attempts) == 1:
            return RequestErrorRetry()
        return await next()

    ctx.on("agent/request-error", retry_once)
    try:
        agent.followup("hi")
        await agent.when_idle()

        assert attempts == ["BOOM"]
        assert provider.calls == 2
        assert len(agent.session.events_of("step/start")) == 1  # 重试在同一 step 内
        assert len(agent.session.events_of("user/message")) == 1
        assert _texts(agent.session) == ["hi", "recovered"]
        assert [event.data.status for event in agent.session.events_of("turn/end")] == ["completed"]
    finally:
        await ctx.dispose()


@run_async
async def test_unrecoverable_error_fails_turn_but_loop_survives() -> None:
    provider = MockProvider()  # 空脚本 → 首次请求即 SCRIPT_EXHAUSTED
    ctx, agent, _ = await _env(provider=provider)
    try:
        agent.followup("hi")
        await agent.when_idle()

        assert [event.data.status for event in agent.session.events_of("turn/end")] == ["error"]
        assert isinstance(agent.last_error, LlmError)
        assert agent.last_error.code == "SCRIPT_EXHAUSTED"
        assert not agent.session.events_of("assistant/message")
        assert len(agent.session.events_of("step/end")) == 1
        assert agent.status == "idle"

        provider.add(text_response("recovered"))
        agent.followup("again")
        await agent.when_idle()

        statuses = [event.data.status for event in agent.session.events_of("turn/end")]
        assert statuses == ["error", "completed"]
        assert _texts(agent.session)[-1] == "recovered"
    finally:
        await ctx.dispose()


# -- 取消 ------------------------------------------------------------------


@run_async
async def test_cancel_mid_stream_logs_interrupted_prefix() -> None:
    provider = ScriptProvider()
    provider.push(("gate", "par"))
    ctx, agent, _ = await _env(provider=provider)
    try:
        agent.followup("hi")
        await _wait_for(lambda: provider.hung)
        agent.cancel()
        await agent.when_idle()

        interrupted = agent.session.events_of("assistant/message")[0].data
        assert interrupted.interrupted is True
        assert message_text(interrupted.message) == "par"
        assert [event.data.status for event in agent.session.events_of("turn/end")] == ["canceled"]
        assert _texts(agent.session) == ["hi", "par"]  # 前缀进入派生历史
        assert not agent.inbox.pending

        provider.push(text_response("after"))
        agent.followup("again")
        await agent.when_idle()
        statuses = [event.data.status for event in agent.session.events_of("turn/end")]
        assert statuses == ["canceled", "completed"]
    finally:
        await ctx.dispose()


@run_async
async def test_cancel_mid_tools_synthesizes_unknown_and_aborted() -> None:
    entered = asyncio.Event()
    release = asyncio.Event()

    async def slow(args: dict) -> str:
        entered.set()
        await release.wait()
        return "late"

    tools = [
        ToolDefinition(
            name="slow",
            description="hangs",
            parameters={"type": "object"},
            execute=slow,
            is_concurrency_safe=True,
        )
    ]
    provider = MockProvider(
        script=[tool_call_response(("slow", {"n": 1}), ("slow", {"n": 2}))]
    )
    ctx, agent, _ = await _env(provider=provider, tools=tools, max_parallel_tool_calls=1)
    try:
        agent.followup("go")
        await _wait_for(entered.is_set)
        agent.cancel()
        await agent.when_idle()

        assert len(agent.session.events_of("tool/call")) == 2  # 模型序全部先落盘
        results = [event.data.message for event in agent.session.events_of("tool/result")]
        assert len(results) == 2
        assert results[0].content == "Error: tool call was interrupted; its outcome is unknown"
        assert results[1].content == "Error: tool call aborted before dispatch"
        assert all(result.is_error for result in results)
        assert [event.data.status for event in agent.session.events_of("turn/end")] == ["canceled"]
    finally:
        await ctx.dispose()


@run_async
async def test_cancel_keep_inbox_preserves_steer() -> None:
    provider = ScriptProvider()
    provider.push(("gate", "one"), ("gate", "two"))
    ctx, agent, _ = await _env(provider=provider)
    try:
        agent.followup("first")
        await _wait_for(lambda: provider.hung)
        agent.steer("second")
        agent.cancel(keep_inbox=True)

        # 保留的 steer 成为新轮次的输入
        await _wait_for(lambda: len(agent.session.events_of("turn/start")) == 2)
        agent.cancel()
        await agent.when_idle()

        statuses = [event.data.status for event in agent.session.events_of("turn/end")]
        assert statuses == ["canceled", "canceled"]
        users = [event.data for event in agent.session.events_of("user/message")]
        assert [message_text(user.message) for user in users] == ["first", "second"]
        assert [user.source for user in users] == ["user", "steer"]
    finally:
        await ctx.dispose()


# -- 并发调度 --------------------------------------------------------------


@run_async
async def test_parallel_safe_tools_overlap() -> None:
    both_started = asyncio.Event()
    seen: set[str] = set()

    def make_tool(name: str) -> ToolDefinition:
        async def execute(args: dict) -> str:
            seen.add(name)
            if len(seen) == 2:
                both_started.set()
            await asyncio.wait_for(both_started.wait(), timeout=1)  # 串行执行会超时
            return f"{name}-done"

        return ToolDefinition(
            name=name,
            description="waits for sibling",
            parameters={"type": "object"},
            execute=execute,
            is_concurrency_safe=True,
        )

    provider = MockProvider(
        script=[
            tool_call_response(("t1", {}), ("t2", {})),
            text_response("done"),
        ]
    )
    ctx, agent, _ = await _env(provider=provider, tools=[make_tool("t1"), make_tool("t2")])
    try:
        agent.followup("go")
        await agent.when_idle()

        results = [event.data.message for event in agent.session.events_of("tool/result")]
        assert [result.content for result in results] == ["t1-done", "t2-done"]  # 真并行才能同时放行
        assert all(not result.is_error for result in results)
    finally:
        await ctx.dispose()


@run_async
async def test_exclusive_barrier_ordering() -> None:
    order: list[str] = []
    both = asyncio.Event()
    safe_seen = 0

    async def exclusive(args: dict) -> str:
        order.append(f"ex{args['n']}-enter")
        await asyncio.sleep(0)
        order.append(f"ex{args['n']}-exit")
        return "ex"

    async def safe(args: dict) -> str:
        nonlocal safe_seen
        name = f"s{args['n']}"
        order.append(f"{name}-enter")
        safe_seen += 1
        if safe_seen == 2:
            both.set()
        await asyncio.wait_for(both.wait(), timeout=1)
        order.append(f"{name}-exit")
        return name

    tools = [
        ToolDefinition("ex", "exclusive", {"type": "object"}, exclusive, is_concurrency_safe=False),
        ToolDefinition("s", "safe", {"type": "object"}, safe, is_concurrency_safe=True),
    ]
    provider = MockProvider(
        script=[
            tool_call_response(("ex", {"n": 1}), ("s", {"n": 1}), ("s", {"n": 2}), ("ex", {"n": 2})),
            text_response("done"),
        ]
    )
    ctx, agent, _ = await _env(provider=provider, tools=tools)
    try:
        agent.followup("go")
        await agent.when_idle()

        assert order[:2] == ["ex1-enter", "ex1-exit"]  # 独占先于批次完成
        assert order[-2:] == ["ex2-enter", "ex2-exit"]  # 批次完成后才轮到独占
        assert set(order[2:-2]) == {"s1-enter", "s1-exit", "s2-enter", "s2-exit"}  # 安全批次交错执行
    finally:
        await ctx.dispose()


# -- Inbox 领取语义与 steer/inject 时机 ------------------------------------


@run_async
async def test_inbox_claim_semantics() -> None:
    inbox = Inbox()
    inbox.enqueue_turn(InboxMessage.text("user", "u1"))
    inbox.enqueue_step(InboxMessage.text("steer", "s1"))
    inbox.enqueue_turn(InboxMessage.text("user", "u2"))
    inbox.enqueue_step(InboxMessage.text("inject", "s2"))

    assert [message.content for message in inbox.claim_for_turn()] == ["s1", "s2", "u1"]
    assert [message.content for message in inbox.claim_for_step()] == []  # next_step 已被领空
    assert [message.content for message in inbox.claim_for_turn()] == ["u2"]
    assert not inbox.pending

    inbox.enqueue_step(InboxMessage.text("steer", "s3"))
    assert [message.content for message in inbox.claim_for_step()] == ["s3"]
    assert [message.content for message in inbox.claim_for_turn()] == []  # next_turn 不动


@run_async
async def test_inject_does_not_wake_but_followup_does() -> None:
    inbox = Inbox()
    inbox.enqueue_step(InboxMessage.text("inject", "x"), wake=False)

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(inbox.wait(), timeout=0.01)
    assert [message.content for message in inbox.claim_for_turn()] == ["x"]  # 不唤醒，但领取可见

    inbox.enqueue_turn(InboxMessage.text("user", "u"))
    await asyncio.wait_for(inbox.wait(), timeout=1)


@run_async
async def test_steer_extends_current_turn() -> None:
    provider = ScriptProvider()
    provider.push(("gate", "part one"), text_response("part two"))
    ctx, agent, _ = await _env(provider=provider)
    try:
        agent.followup("first")
        await _wait_for(lambda: provider.hung)
        agent.steer("second")
        provider.gate.set()
        await agent.when_idle()

        assert len(agent.session.events_of("turn/start")) == 1  # 同一个 turn 内
        assert len(agent.session.events_of("step/start")) == 2  # 多跑了一个 step
        users = [event.data for event in agent.session.events_of("user/message")]
        assert [user.source for user in users] == ["user", "steer"]
        assert _texts(agent.session) == ["first", "part one", "second", "part two"]
    finally:
        await ctx.dispose()


@run_async
async def test_followup_during_turn_starts_next_turn() -> None:
    provider = ScriptProvider()
    provider.push(("gate", "one"), text_response("two"))
    ctx, agent, _ = await _env(provider=provider)
    try:
        agent.followup("first")
        await _wait_for(lambda: provider.hung)
        agent.followup("second")
        provider.gate.set()
        await agent.when_idle()

        assert len(agent.session.events_of("turn/start")) == 2
        assert _texts(agent.session) == ["first", "one", "second", "two"]
        statuses = [event.data.status for event in agent.session.events_of("turn/end")]
        assert statuses == ["completed", "completed"]
    finally:
        await ctx.dispose()
