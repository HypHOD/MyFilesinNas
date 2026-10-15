"""工具子系统：注册表与带把关的执行流水线。

直译自 dsh ``packages/core/tools``（docs/subsystems/tools.zh.md）：

- ToolDefinition = {name, description, parameters(JSON Schema), execute, is_concurrency_safe}；
  ``schemas()`` 是给模型的白名单投影，execute 与回调不外泄；
- 执行流水线（每次调用）：``tools/pre-execute`` waterfall → allow | deny{reason}
  （单调：deny 不可被下游翻回）→ ``tools/execute`` waterfall（环绕真实执行）→
  ``tools/post-execute`` waterfall → accept{content?} | block{feedback}；
- 失败是 ``ToolResultMessage(is_error=True)``，错误以 ``Error: ...`` 文本进入模型
  历史，**失败不终止轮次**；
- execution_mode：默认 exclusive（独占屏障），显式 ``is_concurrency_safe`` 才并行——
  调度发生在 agent_loop（对照 ``packages/core/agent-loop/src/tool-calls.ts``）。

与 dsh 的差异：砍掉审批(ask)/sandbox/结果 schema 校验/concludeTurn；execute 只返回字符串。
"""

from __future__ import annotations

import inspect
import json
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import Any

from mini_harness.container import Context
from mini_harness.events import Disposer
from mini_harness.messages import ToolResultMessage

ToolExecuteFn = Callable[[dict[str, Any]], "str | Awaitable[str]"]


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    parameters: dict[str, Any]
    execute: ToolExecuteFn
    is_concurrency_safe: bool = False


@dataclass(frozen=True)
class ToolCallView:
    """传给拦截监听器的只读调用视图。"""

    call_id: str
    name: str
    arguments: dict[str, Any]
    raw_arguments: str


# -- 决策联合（闭联合，新成员需要更新所有 match 分支） ----------------------


@dataclass(frozen=True)
class PreToolAllow:
    pass


@dataclass(frozen=True)
class PreToolDeny:
    reason: str


PreToolDecision = PreToolAllow | PreToolDeny


@dataclass(frozen=True)
class ToolRunSuccess:
    output: str


@dataclass(frozen=True)
class ToolRunFailure:
    code: str
    message: str


ToolRunOutcome = ToolRunSuccess | ToolRunFailure


@dataclass(frozen=True)
class PostToolAccept:
    content: str | None = None  # None → 采用执行输出原文


@dataclass(frozen=True)
class PostToolBlock:
    feedback: str


PostToolDecision = PostToolAccept | PostToolBlock


class ToolRegistry:
    """注册在 ``ctx.tools``：工具注册表。"""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition) -> Disposer:
        if tool.name in self._tools:
            raise RuntimeError(f"tool already registered: {tool.name!r}")
        self._tools[tool.name] = tool

        def dispose() -> None:
            self._tools.pop(tool.name, None)

        return dispose

    def get(self, name: str) -> ToolDefinition | None:
        return self._tools.get(name)

    def schemas(self) -> tuple[dict[str, Any], ...]:
        """给模型的白名单投影：只有 name/description/parameters。"""
        return tuple(
            {"name": t.name, "description": t.description, "parameters": t.parameters}
            for t in self._tools.values()
        )


async def run_tool_pipeline(
    ctx: Context,
    *,
    call_id: str,
    name: str,
    raw_arguments: str,
) -> ToolResultMessage:
    """跑完三段流水线，产出一条进入模型历史的工具结果。"""
    try:
        parsed = json.loads(raw_arguments) if raw_arguments.strip() else {}
        if not isinstance(parsed, dict):
            raise ValueError("arguments must be a JSON object")
    except ValueError:
        return _failure(call_id, "INVALID_ARGS", f"invalid tool arguments JSON: {raw_arguments!r}")

    tool = ctx.tools.get(name)
    if tool is None:
        return _failure(call_id, "UNKNOWN_TOOL", f"unknown tool: {name}")

    view = ToolCallView(call_id=call_id, name=name, arguments=parsed, raw_arguments=raw_arguments)

    # 第一段：准入（deny 即短路，execute 不会执行）
    pre: PreToolDecision = await ctx.waterfall(
        "tools/pre-execute", view, default=lambda _view: PreToolAllow()
    )
    if isinstance(pre, PreToolDeny):
        return ToolResultMessage(
            tool_call_id=view.call_id, content=f"Error: {pre.reason}", is_error=True
        )

    # 第二段：执行（waterfall 环绕真实分发；监听器可调用 next() 或自行短路）
    async def default_execute(v: ToolCallView, t: ToolDefinition) -> ToolRunOutcome:
        try:
            result = t.execute(dict(v.arguments))
            if inspect.isawaitable(result):
                result = await result
            return ToolRunSuccess(str(result))
        except Exception as exc:  # 工具失败不终止轮次，转为模型可见的错误结果
            return ToolRunFailure(code="EXECUTION_ERROR", message=f"{type(exc).__name__}: {exc}")

    outcome: ToolRunOutcome = await ctx.waterfall("tools/execute", view, tool, default=default_execute)

    # 第三段：结果采纳（block 可以把成功结果改为对模型可见的失败反馈）
    post: PostToolDecision = await ctx.waterfall(
        "tools/post-execute", view, outcome, default=lambda _v, _o: PostToolAccept()
    )

    if isinstance(post, PostToolBlock):
        return _failure(call_id, "BLOCKED", post.feedback)
    if isinstance(outcome, ToolRunFailure):
        return _failure(call_id, outcome.code, outcome.message)

    content = post.content if post.content is not None else outcome.output
    return ToolResultMessage(tool_call_id=call_id, content=content)


def _failure(call_id: str, code: str, message: str) -> ToolResultMessage:
    del code  # code 留在日志语义里；模型只看到稳定的 "Error: ..." 文本
    return ToolResultMessage(tool_call_id=call_id, content=f"Error: {message}", is_error=True)


class ToolsPlugin:
    """提供 ``ctx.tools`` 服务并注册初始工具。"""

    name = "tools"

    def __init__(self, tools: Iterable[ToolDefinition] = ()) -> None:
        self._tools = tuple(tools)

    def apply(self, ctx) -> None:
        registry = ToolRegistry()
        ctx.provide("tools", registry)
        for tool in self._tools:
            ctx.effect(registry.register(tool))
