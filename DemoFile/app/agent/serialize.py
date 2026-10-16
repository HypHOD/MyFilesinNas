"""session 事件 → JSON dict / SSE 帧（HTTP 层消费 append-only 日志的唯一转译点）。

- event_to_dict：把 mini-harness 的 dataclass payload 转成平凡 dict；字段用 camelCase
  与前端契约一致（callId / isError / lastError）。
- 工具调用参数保持**原始 JSON 字符串**（mini-harness 的约定，执行方才解析）——
  SSE 消费端要看结构化就自己 JSON.parse，不在转译层代劳。
- sse_frame：`id`（seq，断线重连可作 Last-Event-ID 对齐 since）、
  `event`（事件类型，前端 addEventListener 用）、`data`（JSON）。
"""

from __future__ import annotations

import json
from typing import Any

from mini_harness.messages import Message, TextBlock, ToolCallBlock
from mini_harness.session import SessionEvent


def message_to_dict(message: Message) -> dict[str, Any]:
    blocks: list[dict[str, Any]] = []
    for block in message.content:
        if isinstance(block, TextBlock):
            blocks.append({"type": "text", "text": block.text})
        elif isinstance(block, ToolCallBlock):
            blocks.append(
                {"type": "tool_call", "id": block.id, "name": block.name, "arguments": block.arguments}
            )
    return {"role": message.role, "content": blocks}


def event_to_dict(event: SessionEvent) -> dict[str, Any]:
    data = event.data
    if event.type == "system/message":
        return {"message": message_to_dict(data)}
    if event.type == "user/message":
        return {"message": message_to_dict(data.message), "source": data.source}
    if event.type == "assistant/message":
        return {
            "turn": data.turn,
            "step": data.step,
            "message": message_to_dict(data.message),
            "interrupted": data.interrupted,
        }
    if event.type == "tool/call":
        return {"callId": data.call_id, "name": data.name, "arguments": data.arguments}
    if event.type == "tool/result":
        return {
            "callId": data.message.tool_call_id,
            "content": data.message.content,
            "isError": data.message.is_error,
        }
    if event.type == "turn/start":
        return {"turn": data.turn}
    if event.type == "turn/end":
        return {"turn": data.turn, "status": data.status}
    if event.type in ("step/start", "step/end"):
        return {"turn": data.turn, "step": data.step}
    return {"repr": repr(data)}


def sse_frame(event: SessionEvent) -> str:
    payload = json.dumps(event_to_dict(event), ensure_ascii=False)
    return f"id: {event.seq}\nevent: {event.type}\ndata: {payload}\n\n"
