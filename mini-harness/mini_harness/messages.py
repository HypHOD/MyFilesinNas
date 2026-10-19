"""消息词汇与流式分片。

实现对齐 dsh ``packages/llm/llm`` 的消息/流式词汇（docs/subsystems/llm-streaming.zh.md）：

- 消息 = ``{role, content: ContentBlock[]}``，块 = text | tool_call；
- 工具调用参数全程保持原始 JSON 字符串，由执行方解析；
- 工具结果不是块，是独立 tool-role 的 ``ToolResultMessage``；
- 流式分片是封闭联合：block_start / text_delta / tool_call_delta / block_end / finish，
  由 BlockAssembler（llm.py）折叠回完整消息。

数据流：llm.py 产生 StreamChunk → BlockAssembler 折叠成 Message / ToolCallBlock
→ agent_loop.py 连同 ToolResultMessage 写入 session.py 日志 → derive_messages()
投影成下一次请求的 ModelMessage 列表。
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
    # 原始 JSON 字符串：流式到达时只是累加，执行前才由 tools.py 解析
    arguments: str


ContentBlock = TextBlock | ToolCallBlock


# -- 消息 -----------------------------------------------------------------


@dataclass(frozen=True)
class Message:
    # 只有 system / user / assistant 三种角色；工具结果使用独立的 ToolResultMessage。
    role: Literal["system", "user", "assistant"]
    content: tuple[ContentBlock, ...]


@dataclass(frozen=True)
class ToolResultMessage:
    # 工具结果不是内容块，而是独立的消息类型；tool_call_id 让模型把结果和调用配对。
    tool_call_id: str
    content: str
    is_error: bool = False  # 失败也只是 Error 文本，不会中断轮次


ModelMessage = Message | ToolResultMessage


def text_message(role: Literal["system", "user", "assistant"], text: str) -> Message:
    return Message(role=role, content=(TextBlock(text),))


def message_text(message: Message) -> str:
    """拼接消息中所有文本块（忽略工具调用块）。"""
    return "".join(block.text for block in message.content if isinstance(block, TextBlock))


def tool_calls_of(message: Message) -> tuple[ToolCallBlock, ...]:
    return tuple(block for block in message.content if isinstance(block, ToolCallBlock))


# -- 流式分片 -------------------------------------------------------------
# 一条流式响应的生命周期（BlockAssembler 按 index 槽位折叠）：
#   BlockStart(index, type) → TextDelta* 或 ToolCallDelta* → BlockEnd(index)
#   ……多个 index 可以交错到达…… → Finish(reason) 结束整条响应
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
    # 结束原因决定收尾策略：normal stop / 还要调工具 / 截断 / 中止 / 错误
    reason: FinishReason


StreamChunk = BlockStart | TextDelta | ToolCallDelta | BlockEnd | Finish
