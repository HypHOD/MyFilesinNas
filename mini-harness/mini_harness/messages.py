"""消息词汇与流式分片。

直译自 dsh ``packages/llm/llm`` 的消息/流式词汇（docs/subsystems/llm-streaming.zh.md）：

- 消息 = ``{role, content: ContentBlock[]}``，块 = text | tool_call；
- 工具调用参数全程保持**原始 JSON 字符串**，由执行方解析；
- 工具结果不是块，是独立 tool-role 的 ``ToolResultMessage``；
- 流式分片是封闭联合：block_start / text_delta / tool_call_delta / block_end / finish，
  由 BlockAssembler（llm.py）折叠回完整消息。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# -- 内容块 ---------------------------------------------------------------


@dataclass(frozen=True)
class TextBlock:
    text: str


@dataclass(frozen=True)
class ToolCallBlock:
    id: str
    name: str
    arguments: str  # 原始 JSON 字符串，不在此处解析


ContentBlock = TextBlock | ToolCallBlock


# -- 消息 -----------------------------------------------------------------


@dataclass(frozen=True)
class Message:
    role: Literal["system", "user", "assistant"]
    content: tuple[ContentBlock, ...]


@dataclass(frozen=True)
class ToolResultMessage:
    tool_call_id: str
    content: str
    is_error: bool = False


ModelMessage = Message | ToolResultMessage


def text_message(role: Literal["system", "user", "assistant"], text: str) -> Message:
    return Message(role=role, content=(TextBlock(text),))


def message_text(message: Message) -> str:
    """拼接消息中所有文本块（忽略工具调用块）。"""
    return "".join(block.text for block in message.content if isinstance(block, TextBlock))


def tool_calls_of(message: Message) -> tuple[ToolCallBlock, ...]:
    return tuple(block for block in message.content if isinstance(block, ToolCallBlock))


# -- 流式分片 -------------------------------------------------------------

FinishReason = Literal["stop", "tool_calls", "max_tokens", "aborted", "error"]


@dataclass(frozen=True)
class BlockStart:
    index: int
    block_type: Literal["text", "tool_call"]


@dataclass(frozen=True)
class TextDelta:
    index: int
    text: str


@dataclass(frozen=True)
class ToolCallDelta:
    index: int
    id: str | None  # 首个分片携带 id/name，后续分片为 None
    name: str | None
    arguments_delta: str


@dataclass(frozen=True)
class BlockEnd:
    index: int


@dataclass(frozen=True)
class Finish:
    reason: FinishReason


StreamChunk = BlockStart | TextDelta | ToolCallDelta | BlockEnd | Finish
