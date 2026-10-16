"""DeepSeek 流式提供方：实现 mini-harness 的 LlmProvider 协议。

mini-harness 自带 MockProvider（脚本化、确定性），接真实模型由宿主补提供方。
本模块把 DeepSeek 的 OpenAI 兼容 SSE 流翻译成 mini_harness.messages 的
StreamChunk 联合，之后由 BlockAssembler 折叠回完整 assistant 消息。

与 mini_harness/llm.py 的协议约定：
  - stream(options) 一次调用 = 一次提供方尝试，失败抛 LlmError(code)；
    库内不重试 —— 重试由 agent/request-error 事件监听器决定；
  - 槽位映射：文本固定占槽 0，工具调用占槽 1 + OpenAI 的 tool_calls[].index
    （BlockAssembler 按槽位折叠；文本槽为空时不会产出空块）;
  - finish_reason：stop→stop / tool_calls→tool_calls / length→max_tokens
    （max_tokens 会让 BlockAssembler 丢弃参数不完整的工具调用）；
  - 流结束但没见到 finish_reason → STREAM_TRUNCATED（截断的响应不能当完成）。
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator, Sequence

import httpx

from mini_harness.llm import GenerateOptions, LlmError
from mini_harness.messages import (
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
    ToolResultMessage,
)

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"

_FINISH_REASONS: dict[str, FinishReason] = {
    "stop": "stop",
    "tool_calls": "tool_calls",
    "length": "max_tokens",
    "content_filter": "error",
}


class DeepSeekProvider:
    """OpenAI 兼容 chat.completions 的流式提供方（DeepSeek 及同协议网关）。"""

    name = "deepseek"

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float = 120.0,
    ) -> None:
        key = api_key or os.environ.get("DEEPSEEK_API_KEY", "")
        if not key:
            raise ValueError("缺少 DEEPSEEK_API_KEY（环境变量或构造参数）")
        self.api_key = key
        self.base_url = (
            base_url or os.environ.get("DEEPSEEK_BASE_URL") or DEFAULT_BASE_URL
        ).rstrip("/")
        self.model = model or os.environ.get("DEEPSEEK_MODEL") or DEFAULT_MODEL
        self.timeout = timeout

    async def stream(self, options: GenerateOptions) -> AsyncIterator[StreamChunk]:
        payload: dict = {
            "model": options.model or self.model,
            "messages": _to_openai_messages(options.messages),
            "stream": True,
        }
        if options.tools:
            payload["tools"] = [
                {"type": "function", "function": dict(tool)} for tool in options.tools
            ]

        started: set[int] = set()
        finish: FinishReason | None = None
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/chat/completions",
                    json=payload,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                ) as response:
                    if response.status_code != 200:
                        body = (await response.aread()).decode("utf-8", "replace")
                        raise LlmError(f"HTTP_{response.status_code}", body[:500])
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue  # 空行 / ": keep-alive" 心跳
                        data = line[len("data:"):].strip()
                        if data == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data)
                        except json.JSONDecodeError:
                            continue  # 容忍解析不了的杂讯行
                        choices = chunk.get("choices") or []
                        if not choices:
                            continue  # usage 之类的尾块
                        choice = choices[0]
                        delta = choice.get("delta") or {}

                        text = delta.get("content")
                        if text:
                            if 0 not in started:
                                started.add(0)
                                yield BlockStart(0, "text")
                            yield TextDelta(0, text)

                        for call in delta.get("tool_calls") or []:
                            slot = 1 + int(call.get("index") or 0)
                            function = call.get("function") or {}
                            if slot not in started:
                                started.add(slot)
                                yield BlockStart(slot, "tool_call")
                            yield ToolCallDelta(
                                index=slot,
                                id=call.get("id"),
                                name=function.get("name"),
                                arguments_delta=function.get("arguments") or "",
                            )

                        reason = choice.get("finish_reason")
                        if reason:
                            mapped = _FINISH_REASONS.get(reason)
                            if mapped is None:
                                raise LlmError("PROVIDER_ERROR", f"未知 finish_reason: {reason!r}")
                            finish = mapped
        except httpx.HTTPError as exc:
            raise LlmError("NETWORK_ERROR", f"{type(exc).__name__}: {exc}") from exc

        if finish is None:
            raise LlmError("STREAM_TRUNCATED", "流已结束但未收到 finish_reason")
        yield Finish(finish)


def _to_openai_messages(messages: Sequence[ModelMessage]) -> list[dict]:
    """mini-harness 消息 → OpenAI chat.completions 消息。

    - assistant 的 ToolCallBlock 还原成 tool_calls[]（arguments 保持原始 JSON 串）；
    - ToolResultMessage → role=tool + tool_call_id；is_error 只影响日志语义，
      文本里的 "Error: ..." 前缀已经表达给模型了，不做额外标注。
    """
    converted: list[dict] = []
    for message in messages:
        if isinstance(message, ToolResultMessage):
            converted.append(
                {"role": "tool", "tool_call_id": message.tool_call_id, "content": message.content}
            )
            continue
        assert isinstance(message, Message)
        text = "".join(block.text for block in message.content if isinstance(block, TextBlock))
        if message.role == "assistant":
            entry: dict = {"role": "assistant", "content": text or None}
            calls = [block for block in message.content if isinstance(block, ToolCallBlock)]
            if calls:
                entry["tool_calls"] = [
                    {
                        "id": block.id,
                        "type": "function",
                        "function": {"name": block.name, "arguments": block.arguments},
                    }
                    for block in calls
                ]
            converted.append(entry)
        else:
            converted.append({"role": message.role, "content": text})
    return converted
