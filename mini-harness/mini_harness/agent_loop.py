"""默认驱动器：turn/step 状态机 + 拦截点 + 取消合成。

直译自 dsh ``packages/core/agent-loop``（docs/subsystems/agent-lifecycle.zh.md）：

- 一次 followup = 一个 turn；turn 内含若干 step；step 产出了工具调用或有新输入
  则续 step，否则过 ``agent/turn-stopping``（serial）后收口 ``turn/end``；
- 拦截点：``agent/pre-step``（waterfall：enter | reject，决定领取的输入是否入账）、
  ``agent/request``（waterfall：可改写 provider/model）、``agent/request-error``
  （waterfall：retry 同一 step 或上抛）；
- 工具调度（对照 ``packages/core/agent-loop/src/tool-calls.ts``）：先按模型序把
  全部 ``tool/call`` 落盘；默认独占屏障逐个执行，连续一段显式
  ``is_concurrency_safe`` 的调用走有界并行池；结果按模型序提交；
- 取消：已开工的调用合成「outcome is unknown」，未派发的合成
  「aborted before dispatch」——保证日志里每个 tool/call 都有对应结果，
  失败与取消都不终止 loop（对照 agent.ts）。

与 dsh 的差异：无重试预算、usage 记账、实时流帧；request-error 重试不设次数
上限，由监听器把关。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Literal

from mini_harness.agent import Agent, InboxMessage
from mini_harness.container import Context
from mini_harness.llm import BlockAssembler, GenerateOptions, LlmError
from mini_harness.messages import (
    Message,
    TextBlock,
    ToolCallBlock,
    ToolResultMessage,
    text_message,
)
from mini_harness.session import (
    AssistantMessageData,
    StepEnd,
    StepStart,
    ToolCallData,
    ToolResultData,
    TurnEnd,
    TurnStart,
    UserMessageData,
    derive_messages,
)
from mini_harness.tools import run_tool_pipeline


# -- 拦截点决策（闭联合） --------------------------------------------------


@dataclass(frozen=True)
class PreStepEnter:
    messages: tuple[InboxMessage, ...]


@dataclass(frozen=True)
class PreStepReject:
    reason: str


PreStepDecision = PreStepEnter | PreStepReject


@dataclass(frozen=True)
class RequestSpec:
    provider: str
    model: str


@dataclass(frozen=True)
class RequestErrorRetry:
    """重试同一 step（丢弃已到达的分片，重新发起请求）。"""


@dataclass(frozen=True)
class RequestErrorRaise:
    """上抛为轮次错误（turn/end status=error），loop 继续存活。"""


RequestErrorDecision = RequestErrorRetry | RequestErrorRaise


@dataclass
class _TurnState:
    """轮次进行中的易失状态；取消合成依赖它知道「到哪了」。"""

    turn: int
    step_no: int = 0
    assembler: BlockAssembler | None = None
    streaming_step: int | None = None
    dispatched: dict[str, bool] = field(default_factory=dict)  # call_id -> 是否已开工


class AgentLoop:
    """默认驱动器：消费 inbox，跑 turn/step 状态机。"""

    def __init__(self, ctx: Context, *, max_parallel_tool_calls: int = 10) -> None:
        self._ctx = ctx
        self._max_parallel_tool_calls = max_parallel_tool_calls

    def start(self, agent: Agent) -> asyncio.Task[None]:
        return asyncio.get_running_loop().create_task(self._run(agent), name=f"agent-loop:{agent.id}")

    # -- 主循环 ----------------------------------------------------------

    async def _run(self, agent: Agent) -> None:
        try:
            while not agent.closed:
                agent.mark_idle()
                try:
                    await agent.inbox.wait()
                except asyncio.CancelledError:
                    if agent.closed:
                        break
                    self._handle_cancel(agent)
                    continue
                if not agent.inbox.pending:
                    continue
                agent.mark_running()
                await self._run_turn(agent)
        finally:
            agent.mark_idle()

    async def _run_turn(self, agent: Agent) -> None:
        session = agent.session
        turn_no = len(session.events_of("turn/start")) + 1
        claimed = agent.inbox.claim_for_turn()
        if not claimed:
            return
        session.append("turn/start", TurnStart(turn=turn_no))
        state = _TurnState(turn=turn_no)
        status: Literal["completed", "canceled", "error"] = "completed"
        owed = False  # 是否欠一个 step（有已入账未处理的输入或工具调用）
        try:
            while True:
                if claimed:
                    decision: PreStepDecision = await self._ctx.waterfall(
                        "agent/pre-step",
                        agent,
                        tuple(claimed),
                        default=lambda _agent, messages: PreStepEnter(messages=tuple(messages)),
                    )
                    claimed = []
                    if isinstance(decision, PreStepEnter) and decision.messages:
                        self._enter_messages(agent, turn_no, decision.messages)
                        owed = True
                if not owed:
                    break
                state.step_no += 1
                owed = await self._run_step(agent, turn_no, state.step_no, state)
                if owed:
                    claimed = agent.inbox.claim_for_step()
                    continue
                await self._ctx.serial("agent/turn-stopping", agent)
                claimed = agent.inbox.claim_for_step()
                if claimed:
                    continue
                break
        except asyncio.CancelledError:
            status = "canceled"
            self._synthesize_interrupted(agent, state)
            self._handle_cancel(agent)
        except Exception as exc:
            status = "error"
            agent.last_error = exc
            self._synthesize_interrupted(agent, state)
        finally:
            session.append("turn/end", TurnEnd(turn=turn_no, status=status))

    # -- 单个 step -------------------------------------------------------

    async def _run_step(self, agent: Agent, turn_no: int, step_no: int, state: _TurnState) -> bool:
        session = agent.session
        session.append("step/start", StepStart(turn=turn_no, step=step_no))
        had_tools = False
        try:
            calls = await self._generate(agent, turn_no, step_no, state)
            had_tools = bool(calls)
            if calls:
                await self._run_tool_calls(agent, state, calls)
        finally:
            session.append("step/end", StepEnd(turn=turn_no, step=step_no))
        return had_tools

    async def _generate(
        self, agent: Agent, turn_no: int, step_no: int, state: _TurnState
    ) -> tuple[ToolCallBlock, ...]:
        session = agent.session
        while True:  # 同一 step 内的请求重试循环
            spec: RequestSpec = await self._ctx.waterfall(
                "agent/request",
                agent,
                default=lambda a: RequestSpec(provider=a.provider, model=a.model),
            )
            assembler = BlockAssembler()
            state.assembler = assembler
            state.streaming_step = step_no
            try:
                provider = self._ctx.llm.get(spec.provider)
                options = GenerateOptions(
                    provider=spec.provider,
                    model=spec.model,
                    messages=tuple(derive_messages(session)),
                    tools=self._ctx.tools.schemas(),
                )
                async for chunk in provider.stream(options):
                    assembler.push(chunk)
            except LlmError as exc:
                if isinstance(await self._on_request_error(agent, exc), RequestErrorRetry):
                    continue
                raise
            outcome = assembler.outcome()
            if outcome.finish_reason == "error":
                exc = LlmError("STREAM_ERROR", "provider reported an error finish")
                if isinstance(await self._on_request_error(agent, exc), RequestErrorRetry):
                    continue
                raise exc
            session.append(
                "assistant/message",
                AssistantMessageData(turn=turn_no, step=step_no, message=outcome.message),
            )
            state.assembler = None
            state.streaming_step = None
            return tuple(
                block for block in outcome.message.content if isinstance(block, ToolCallBlock)
            )

    async def _on_request_error(self, agent: Agent, exc: LlmError) -> RequestErrorDecision:
        return await self._ctx.waterfall(
            "agent/request-error",
            agent,
            exc,
            default=lambda _agent, _exc: RequestErrorRaise(),
        )

    # -- 工具调度（对照 tool-calls.ts：独占屏障 + 有界并行池） ------------

    async def _run_tool_calls(
        self, agent: Agent, state: _TurnState, calls: tuple[ToolCallBlock, ...]
    ) -> None:
        session = agent.session
        # 先按模型序把全部调用落盘：模型可见即已记录（取消合成才有对象可补齐）
        for call in calls:
            session.append(
                "tool/call", ToolCallData(call_id=call.id, name=call.name, arguments=call.arguments)
            )
            state.dispatched[call.id] = False

        index = 0
        while index < len(calls):
            call = calls[index]
            tool = self._ctx.tools.get(call.name)
            if tool is None or not tool.is_concurrency_safe:
                state.dispatched[call.id] = True
                result = await run_tool_pipeline(
                    self._ctx, call_id=call.id, name=call.name, raw_arguments=call.arguments
                )
                self._commit(agent, state, result)
                index += 1
                continue
            # 连续的一段并发安全调用组成一个批次，走有界并行池
            batch: list[ToolCallBlock] = []
            while index < len(calls):
                candidate = calls[index]
                candidate_tool = self._ctx.tools.get(candidate.name)
                if candidate_tool is None or not candidate_tool.is_concurrency_safe:
                    break
                batch.append(candidate)
                index += 1
            for result in await self._run_batch(state, batch):
                self._commit(agent, state, result)

    async def _run_batch(
        self, state: _TurnState, batch: list[ToolCallBlock]
    ) -> list[ToolResultMessage]:
        semaphore = asyncio.Semaphore(self._max_parallel_tool_calls)

        async def run_one(call: ToolCallBlock) -> ToolResultMessage:
            async with semaphore:
                state.dispatched[call.id] = True
                return await run_tool_pipeline(
                    self._ctx, call_id=call.id, name=call.name, raw_arguments=call.arguments
                )

        return await asyncio.gather(*(run_one(call) for call in batch))

    def _commit(self, agent: Agent, state: _TurnState, result: ToolResultMessage) -> None:
        agent.session.append("tool/result", ToolResultData(message=result))
        state.dispatched.pop(result.tool_call_id, None)

    # -- 输入入账与取消合成 ----------------------------------------------

    def _enter_messages(
        self, agent: Agent, turn_no: int, messages: tuple[InboxMessage, ...]
    ) -> None:
        session = agent.session
        if agent.system_prompt and not session.events_of("system/message"):
            session.append("system/message", text_message("system", agent.system_prompt))
        for message in messages:
            session.append(
                "user/message",
                UserMessageData(
                    message=text_message("user", message.content), source=message.source
                ),
            )

    def _synthesize_interrupted(self, agent: Agent, state: _TurnState) -> None:
        """取消/出错时的日志收口：已到达的文本前缀落 interrupted 消息，
        未提交的工具调用补合成失败结果。"""
        session = agent.session
        assembler = state.assembler
        if assembler is not None and state.streaming_step is not None and assembler.delivered_text:
            session.append(
                "assistant/message",
                AssistantMessageData(
                    turn=state.turn,
                    step=state.streaming_step,
                    message=Message(role="assistant", content=(TextBlock(assembler.delivered_text),)),
                    interrupted=True,
                ),
            )
        state.assembler = None
        state.streaming_step = None
        for call_id, started in state.dispatched.items():
            content = (
                "Error: tool call was interrupted; its outcome is unknown"
                if started
                else "Error: tool call aborted before dispatch"
            )
            session.append(
                "tool/result",
                ToolResultData(
                    message=ToolResultMessage(tool_call_id=call_id, content=content, is_error=True)
                ),
            )
        state.dispatched.clear()

    def _handle_cancel(self, agent: Agent) -> None:
        if not agent.take_cancel_keep_inbox():
            agent.inbox.clear()


class AgentLoopPlugin:
    """默认驱动器插件：提供 ``agent_loop`` 服务并注册 driver。"""

    name = "agent-loop"
    inject = ("agents", "tools", "llm")

    def __init__(self, max_parallel_tool_calls: int = 10) -> None:
        self._max_parallel_tool_calls = max_parallel_tool_calls

    def apply(self, ctx: Context) -> None:
        loop = AgentLoop(ctx, max_parallel_tool_calls=self._max_parallel_tool_calls)
        ctx.provide("agent_loop", loop)
        ctx.effect(ctx.agents.register_driver(loop))
