"""工具流水线、决策语义与 LLM 分片折叠测试。"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from conftest import run_async
from mini_harness.container import Context
from mini_harness.llm import (
    BlockAssembler,
    GenerateOptions,
    LlmError,
    MockProvider,
    text_response,
    tool_call_response,
)
from mini_harness.messages import (
    BlockEnd,
    BlockStart,
    Finish,
    TextDelta,
    ToolCallDelta,
)
from mini_harness.tools import (
    PostToolAccept,
    PostToolBlock,
    PreToolAllow,
    PreToolDeny,
    ToolDefinition,
    ToolRegistry,
    run_tool_pipeline,
)


def _echo_tool(fail: bool = False) -> ToolDefinition:
    def execute(args: dict) -> str:
        if fail:
            raise ValueError("boom")
        return f"echo:{args.get('text', '')}"

    return ToolDefinition(
        name="echo",
        description="echo text back",
        parameters={"type": "object", "properties": {"text": {"type": "string"}}},
        execute=execute,
        is_concurrency_safe=True,
    )


async def _make_ctx(tools: list[ToolDefinition] | None = None) -> Context:
    ctx = Context()
    registry = ToolRegistry()
    ctx.provide("tools", registry)
    for tool in tools or []:
        registry.register(tool)
    await ctx.ready()
    return ctx


# -- 注册表 ---------------------------------------------------------------


@run_async
async def test_schemas_projection_whitelists_fields() -> None:
    registry = ToolRegistry()
    registry.register(_echo_tool())

    schemas = registry.schemas()

    assert len(schemas) == 1
    assert set(schemas[0]) == {"name", "description", "parameters"}


# -- 流水线：三段 waterfall -----------------------------------------------


@run_async
async def test_pipeline_happy_path() -> None:
    ctx = await _make_ctx([_echo_tool()])

    result = await run_tool_pipeline(ctx, call_id="c1", name="echo", raw_arguments='{"text": "hi"}')

    assert result.tool_call_id == "c1"
    assert result.content == "echo:hi"
    assert result.is_error is False


@run_async
async def test_pre_execute_deny_short_circuits_execution() -> None:
    ctx = await _make_ctx([_echo_tool()])
    executed: list[str] = []

    async def guard(view, next):
        if view.name == "echo":
            return PreToolDeny(reason="echo is banned")
        return await next()

    async def spy(view, tool, next):
        executed.append(view.name)
        return await next()

    ctx.on("tools/pre-execute", guard)
    ctx.on("tools/execute", spy)

    result = await run_tool_pipeline(ctx, call_id="c1", name="echo", raw_arguments="{}")

    assert result.is_error is True
    assert result.content == "Error: echo is banned"
    assert executed == []  # deny 单调：下游与真实执行都没跑


@run_async
async def test_deny_is_monotonic_first_deny_wins() -> None:
    ctx = await _make_ctx([_echo_tool()])
    trace: list[str] = []

    async def denier(view, next):
        trace.append("denier")
        return PreToolDeny(reason="no")

    async def would_allow(view, next):
        trace.append("would_allow")
        return PreToolAllow()

    ctx.on("tools/pre-execute", denier)
    ctx.on("tools/pre-execute", would_allow)

    result = await run_tool_pipeline(ctx, call_id="c1", name="echo", raw_arguments="{}")

    assert result.is_error is True
    assert trace == ["denier"]  # 短路后下游监听器不执行


@run_async
async def test_pre_execute_listener_may_delegate_with_allow() -> None:
    ctx = await _make_ctx([_echo_tool()])

    async def observer(view, next):
        decision = await next()
        if isinstance(decision, PreToolDeny):
            return PreToolDeny(reason=f"observed: {decision.reason}")
        return decision

    ctx.on("tools/pre-execute", observer)

    result = await run_tool_pipeline(ctx, call_id="c1", name="echo", raw_arguments='{"text": "ok"}')

    assert result.content == "echo:ok"


@run_async
async def test_execute_waterfall_wraps_real_call() -> None:
    ctx = await _make_ctx([_echo_tool()])
    order: list[str] = []

    async def timer(view, tool, next):
        order.append("before")
        outcome = await next()
        order.append("after")
        return outcome

    ctx.on("tools/execute", timer)

    result = await run_tool_pipeline(ctx, call_id="c1", name="echo", raw_arguments='{"text": "x"}')

    assert order == ["before", "after"]
    assert result.content == "echo:x"


@run_async
async def test_post_execute_block_turns_success_into_error() -> None:
    ctx = await _make_ctx([_echo_tool()])

    async def auditor(view, outcome, next):
        return PostToolBlock(feedback="output rejected by auditor")

    ctx.on("tools/post-execute", auditor)

    result = await run_tool_pipeline(ctx, call_id="c1", name="echo", raw_arguments="{}")

    assert result.is_error is True
    assert result.content == "Error: output rejected by auditor"


@run_async
async def test_post_execute_accept_can_replace_content() -> None:
    ctx = await _make_ctx([_echo_tool()])

    async def redactor(view, outcome, next):
        return PostToolAccept(content="[redacted]")

    ctx.on("tools/post-execute", redactor)

    result = await run_tool_pipeline(ctx, call_id="c1", name="echo", raw_arguments="{}")

    assert result.content == "[redacted]"
    assert result.is_error is False


@run_async
async def test_execution_exception_becomes_error_result() -> None:
    ctx = await _make_ctx([_echo_tool(fail=True)])

    result = await run_tool_pipeline(ctx, call_id="c1", name="echo", raw_arguments="{}")

    assert result.is_error is True
    assert result.content == "Error: ValueError: boom"


@run_async
async def test_unknown_tool_and_invalid_args() -> None:
    ctx = await _make_ctx([_echo_tool()])

    unknown = await run_tool_pipeline(ctx, call_id="c1", name="nope", raw_arguments="{}")
    invalid = await run_tool_pipeline(ctx, call_id="c2", name="echo", raw_arguments="{not json")

    assert unknown.is_error is True
    assert unknown.content == "Error: unknown tool: nope"
    assert unknown.tool_call_id == "c1"
    assert invalid.is_error is True
    assert "invalid tool arguments" in invalid.content


# -- Mock 提供方与分片折叠 -------------------------------------------------


async def _collect(provider: MockProvider, **overrides) -> list:
    options = GenerateOptions(
        provider=provider.name, model="m", messages=(), tools=(), **overrides
    )
    return [chunk async for chunk in provider.stream(options)]


@run_async
async def test_mock_provider_scripts_and_exhausts() -> None:
    provider = MockProvider(script=[text_response("hello")])

    chunks = await _collect(provider)
    assert any(isinstance(c, TextDelta) and c.text == "hello" for c in chunks)

    with pytest.raises(LlmError) as excinfo:
        await _collect(provider)
    assert excinfo.value.code == "SCRIPT_EXHAUSTED"


@run_async
async def test_mock_provider_tool_call_response_shape() -> None:
    provider = MockProvider(script=[tool_call_response(("read_file", {"path": "a.txt"}))])

    chunks = await _collect(provider)

    starts = [c for c in chunks if isinstance(c, BlockStart)]
    deltas = [c for c in chunks if isinstance(c, ToolCallDelta)]
    assert starts == [BlockStart(0, "tool_call")]
    assert deltas[0].name == "read_file"
    assert deltas[0].id is not None
    assert chunks[-1] == Finish("tool_calls")


def test_assembler_folds_text() -> None:
    assembler = BlockAssembler()
    for chunk in [BlockStart(0, "text"), TextDelta(0, "Hel"), TextDelta(0, "lo"), BlockEnd(0), Finish("stop")]:
        assembler.push(chunk)

    outcome = assembler.outcome()
    assert outcome.finish_reason == "stop"
    assert outcome.message.content[0].text == "Hello"
    assert assembler.delivered_text == "Hello"


def test_assembler_folds_tool_call_arguments_across_deltas() -> None:
    assembler = BlockAssembler()
    assembler.push(BlockStart(0, "tool_call"))
    assembler.push(ToolCallDelta(0, "call_1", "read_file", '{"path":'))
    assembler.push(ToolCallDelta(0, None, None, ' "a.txt"}'))
    assembler.push(BlockEnd(0))
    assembler.push(Finish("tool_calls"))

    outcome = assembler.outcome()
    call = outcome.message.content[0]
    assert call.id == "call_1"
    assert call.name == "read_file"
    assert call.arguments == '{"path": "a.txt"}'


def test_assembler_drops_tool_calls_on_max_tokens() -> None:
    assembler = BlockAssembler()
    assembler.push(BlockStart(0, "tool_call"))
    assembler.push(ToolCallDelta(0, "c1", "echo", '{"text": "trunc'))
    assembler.push(Finish("max_tokens"))

    outcome = assembler.outcome()
    assert outcome.finish_reason == "max_tokens"
    assert outcome.message.content == ()  # 参数不完整，整块丢弃
