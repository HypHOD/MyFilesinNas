"""仅追加的会话事件日志与模型历史投影。

直译自 dsh ``packages/core/session``（docs/subsystems/session.zh.md）：

- ``SessionEvent{type, seq, time, data}``：seq 单调递增，日志仅追加；
- 核心事件：system/message、user/message、assistant/message、tool/call、tool/result、
  turn/start、turn/end、step/start、step/end；
- ``derive_messages()`` 是纯投影：只有 surface 消息进入模型历史——user 消息、非空
  assistant 消息、tool result；turn/step 边界事件与 tool/call（已包含在 assistant
  消息的块里）不投影。

核心不变式「模型可见即已记录」：任何到达模型请求的内容都必须能从这份日志重建。

与 dsh 的差异：纯内存（无 JSONL 持久化/迁移/resume/fork）、无 surface replace 压缩
操作、无 system 节点协调（system/message 简单投影）。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Literal

from mini_harness.messages import Message, ModelMessage, ToolResultMessage


@dataclass(frozen=True)
class SessionEvent:
    type: str
    seq: int
    time: int  # epoch 毫秒
    data: Any


# -- 核心事件的 payload ---------------------------------------------------


@dataclass(frozen=True)
class TurnStart:
    turn: int


@dataclass(frozen=True)
class TurnEnd:
    turn: int
    status: Literal["completed", "canceled", "error"]


@dataclass(frozen=True)
class StepStart:
    turn: int
    step: int


@dataclass(frozen=True)
class StepEnd:
    turn: int
    step: int


@dataclass(frozen=True)
class UserMessageData:
    message: Message
    source: str  # 生产者标识：user / steer / inject / 插件名


@dataclass(frozen=True)
class AssistantMessageData:
    turn: int
    step: int
    message: Message
    interrupted: bool = False


@dataclass(frozen=True)
class ToolCallData:
    call_id: str
    name: str
    arguments: str  # 原始 JSON 字符串


@dataclass(frozen=True)
class ToolResultData:
    message: ToolResultMessage


NotifyFn = Callable[["Session", SessionEvent], None]


@dataclass
class Session:
    """仅追加的事件日志。所有模型可见事实都从这里派生。"""

    id: str
    _events: list[SessionEvent] = field(default_factory=list, init=False)
    _notify: NotifyFn | None = field(default=None, init=False)

    def set_notify(self, notify: NotifyFn) -> None:
        """安装追加回调（用于把 session/event 广播给观察者）。"""
        self._notify = notify

    @property
    def events(self) -> tuple[SessionEvent, ...]:
        return tuple(self._events)

    def append(self, type: str, data: Any) -> SessionEvent:
        event = SessionEvent(type=type, seq=len(self._events), time=int(time.time() * 1000), data=data)
        self._events.append(event)
        if self._notify is not None:
            self._notify(self, event)
        return event

    def events_of(self, type: str) -> tuple[SessionEvent, ...]:
        return tuple(event for event in self._events if event.type == type)


def derive_messages(session: Session) -> list[ModelMessage]:
    """从日志投影模型历史（纯函数，可随时重放）。"""
    messages: list[ModelMessage] = []
    for event in session.events:
        if event.type == "system/message":
            messages.append(event.data)
        elif event.type == "user/message":
            messages.append(event.data.message)
        elif event.type == "assistant/message":
            message: Message = event.data.message
            if message.content:  # 空内容不进入派生历史
                messages.append(message)
        elif event.type == "tool/result":
            messages.append(event.data.message)
        # 其余事件（turn/step 边界、tool/call 等）不投影
    return messages
