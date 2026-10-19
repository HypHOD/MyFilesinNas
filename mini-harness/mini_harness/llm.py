"""LLM seam：提供方协议、流式分片折叠器与脚本化 Mock 提供方。

直译自 dsh ``packages/llm/llm``（docs/subsystems/llm-streaming.zh.md）：

- 提供方最小形状：``stream(options) -> AsyncIterator[StreamChunk]``；
- 一次调用 = 一次提供方尝试，**库内不重试**（重试走 ``agent/request-error`` 事件）；
- 失败抛 ``LlmError(code)``，code 用于消费方路由；
- BlockAssembler 把分片折叠回完整 assistant 消息
  （对照 ``packages/llm/llm/src/assembler.ts``）。

与 dsh 的差异：多适配器路由简化为按 name 查找；砍掉 usage 计量、推理/图片块、
prepareCall、llm-retry 服务；保留 ``max_tokens`` 截断时丢弃工具调用的规则。

阅读提示：``agent_loop._generate()`` 的一次请求 = 本文件的
``provider.stream()`` + ``BlockAssembler`` 折叠。重试不在这里——``LlmError``
抛给 ``agent/request-error`` 事件决定。MockProvider 让 demo/测试无需网络，
按脚本逐条吐出分片。
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator, Iterable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from mini_harness.events import Disposer
from mini_harness.messages import (
    BlockEnd,
    BlockStart,
    Finish,
    FinishReason,
    Message,
    ModelMessage,
    StreamChunk,
    TextBlock,
    TextDelta,
    ToolCallBlock,
    ToolCallDelta,
)


class LlmError(Exception):
    """提供方调用失败；code 是稳定的路由标识。"""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code


@dataclass(frozen=True)
class GenerateOptions:
    provider: str
    model: str
    messages: tuple[ModelMessage, ...]  # 来自 session.derive_messages()
    tools: tuple[dict[str, Any], ...]   # 来自 tools.schemas()（只有白名单字段）


class LlmProvider(Protocol):
    """提供方协议：一次调用产出一条流式响应。"""

    name: str

    def stream(self, options: GenerateOptions) -> AsyncIterator[StreamChunk]: ...


@dataclass(frozen=True)
class AssistantOutcome:
    message: Message
    finish_reason: FinishReason


class BlockAssembler:
    """按 ``index`` 槽位折叠流式分片，还原一条 assistant 消息。

    规则（对照 dsh assembler）：首个 tool_call 分片携带 id/name，后续只带
    arguments_delta；参数全程保持原始字符串；``max_tokens`` 截断时丢弃全部
    工具调用（参数不完整，不可安全执行）。
    """

    def __init__(self) -> None:
        # index → 槽位；不同 index 的文本块/工具调用可以交错到达，最终按 index 排序。
        self._slots: dict[int, dict[str, Any]] = {}
        self._finish_reason: FinishReason | None = None
        self._text_prefix = ""  # 全部文本的已到达前缀（取消时落 interrupted 消息用）

    def push(self, chunk: StreamChunk) -> None:
        if isinstance(chunk, BlockStart):
            # 新开一个 index 槽位；后续 delta 都往这个槽里累积
            self._slots[chunk.index] = {
                "type": chunk.block_type,
                "text": "",
                "id": None,
                "name": None,
                "args": "",
            }
        elif isinstance(chunk, TextDelta):
            slot = self._slots[chunk.index]
            slot["text"] += chunk.text
            self._text_prefix += chunk.text  # 同时维护取消时用的文本前缀
        elif isinstance(chunk, ToolCallDelta):
            slot = self._slots[chunk.index]
            if chunk.id is not None:  # 首个分片携带 id/name
                slot["id"] = chunk.id
            if chunk.name is not None:
                slot["name"] = chunk.name
            slot["args"] += chunk.arguments_delta  # 参数只是字符串拼接，解析在执行前
        elif isinstance(chunk, BlockEnd):
            pass  # 槽位已足够自描述，无需额外收尾
        elif isinstance(chunk, Finish):
            # 结束原因留给 outcome() 决定收尾策略
            self._finish_reason = chunk.reason

    @property
    def delivered_text(self) -> str:
        """已到达的文本前缀（取消时落 interrupted 消息用）。"""
        return self._text_prefix

    def outcome(self) -> AssistantOutcome:
        blocks: list[TextBlock | ToolCallBlock] = []
        # max_tokens 截断时参数不完整，工具调用不可安全执行 → 全部丢弃（对照 dsh assembler）
        drop_tool_calls = self._finish_reason == "max_tokens"
        for index in sorted(self._slots):
            slot = self._slots[index]
            if slot["type"] == "text":
                if slot["text"]:
                    blocks.append(TextBlock(slot["text"]))
            elif not drop_tool_calls:
                blocks.append(
                    ToolCallBlock(id=slot["id"] or "", name=slot["name"] or "", arguments=slot["args"])
                )
        return AssistantOutcome(
            message=Message(role="assistant", content=tuple(blocks)),
            finish_reason=self._finish_reason or "stop",
        )


# -- 脚本化 Mock 提供方 ----------------------------------------------------


@dataclass(frozen=True)
class ScriptedResponse:
    chunks: tuple[StreamChunk, ...]


def text_response(text: str) -> ScriptedResponse:
    """构造一条纯文本响应。"""
    return ScriptedResponse((BlockStart(0, "text"), TextDelta(0, text), BlockEnd(0), Finish("stop")))


def tool_call_response(*calls: tuple[str, dict[str, Any]]) -> ScriptedResponse:
    """构造一条工具调用响应：``tool_call_response(("read_file", {"path": "a.txt"}), ...)``。"""
    chunks: list[StreamChunk] = []
    for index, (name, arguments) in enumerate(calls):
        call_id = f"call_{uuid.uuid4().hex[:8]}"
        chunks.extend(
            [
                BlockStart(index, "tool_call"),
                ToolCallDelta(index, call_id, name, json.dumps(arguments, ensure_ascii=False)),
                BlockEnd(index),
            ]
        )
    chunks.append(Finish("tool_calls"))
    return ScriptedResponse(tuple(chunks))


class MockProvider:
    """脚本化提供方：按预设顺序逐条演出响应。确定性、无网络、无 key。"""

    def __init__(self, name: str = "mock", script: Sequence[ScriptedResponse] = ()) -> None:
        self.name = name
        self._script = list(script)

    def add(self, response: ScriptedResponse) -> None:
        self._script.append(response)

    async def stream(self, options: GenerateOptions) -> AsyncIterator[StreamChunk]:
        # 脚本化演出：每次请求弹出一条预设响应；耗尽就报 SCRIPT_EXHAUSTED（测试可断言）。
        if not self._script:
            raise LlmError("SCRIPT_EXHAUSTED", "mock provider has no scripted response left")
        response = self._script.pop(0)
        for chunk in response.chunks:
            await asyncio.sleep(0)  # 让出事件循环，模拟分片逐步到达
            yield chunk


# -- 服务与插件 ------------------------------------------------------------


class LlmService:
    """注册在 ``ctx.llm``：按 name 注册与查找提供方。"""

    def __init__(self) -> None:
        self._providers: dict[str, LlmProvider] = {}

    def register(self, provider: LlmProvider) -> Disposer:
        # 与 ToolRegistry 同一套模式：注册返回 disposer，由插件作用域负责撤销。
        if provider.name in self._providers:
            raise RuntimeError(f"llm provider already registered: {provider.name!r}")
        self._providers[provider.name] = provider

        def dispose() -> None:
            self._providers.pop(provider.name, None)

        return dispose

    def get(self, name: str) -> LlmProvider:
        provider = self._providers.get(name)
        if provider is None:
            raise LlmError("NO_PROVIDER", f"no llm provider registered for {name!r}")
        return provider


class LlmPlugin:
    """提供 ``ctx.llm`` 服务并注册初始提供方。"""

    name = "llm"

    def __init__(self, providers: Iterable[LlmProvider] = ()) -> None:
        self._providers = tuple(providers)

    def apply(self, ctx) -> None:
        service = LlmService()
        ctx.provide("llm", service)
        for provider in self._providers:
            ctx.effect(service.register(provider))
