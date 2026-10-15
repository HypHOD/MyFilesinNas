"""会话日志与模型历史投影测试。"""

from __future__ import annotations

from conftest import run_async
from mini_harness.messages import Message, TextBlock, ToolCallBlock, ToolResultMessage
from mini_harness.session import (
    AssistantMessageData,
    Session,
    StepEnd,
    StepStart,
    ToolCallData,
    ToolResultData,
    TurnEnd,
    TurnStart,
    UserMessageData,
    derive_messages,
)


def _session() -> Session:
    return Session(id="s1")


def test_seq_is_monotonic_and_envelope_is_filled() -> None:
    session = _session()
    first = session.append("turn/start", TurnStart(turn=1))
    second = session.append("step/start", StepStart(turn=1, step=1))

    assert first.seq == 0
    assert second.seq == 1
    assert first.time > 0
    assert session.events == (first, second)


def test_derive_projects_only_surface_events() -> None:
    session = _session()
    system = Message(role="system", content=(TextBlock("you are a bot"),))
    user = Message(role="user", content=(TextBlock("hi"),))
    assistant = Message(role="assistant", content=(TextBlock("hello"),))
    result = ToolResultMessage(tool_call_id="c1", content="file content")

    session.append("turn/start", TurnStart(turn=1))
    session.append("system/message", system)
    session.append("user/message", UserMessageData(message=user, source="user"))
    session.append("step/start", StepStart(turn=1, step=1))
    session.append("assistant/message", AssistantMessageData(turn=1, step=1, message=assistant))
    session.append("tool/call", ToolCallData(call_id="c1", name="read_file", arguments="{}"))
    session.append("tool/result", ToolResultData(message=result))
    session.append("step/end", StepEnd(turn=1, step=1))
    session.append("turn/end", TurnEnd(turn=1, status="completed"))

    assert derive_messages(session) == [system, user, assistant, result]


def test_derive_skips_empty_assistant_message() -> None:
    session = _session()
    empty = Message(role="assistant", content=())
    session.append("assistant/message", AssistantMessageData(turn=1, step=1, message=empty))

    assert derive_messages(session) == []


def test_derive_keeps_interrupted_assistant_prefix() -> None:
    session = _session()
    partial = Message(role="assistant", content=(TextBlock("I was say"),))
    session.append(
        "assistant/message",
        AssistantMessageData(turn=1, step=1, message=partial, interrupted=True),
    )

    assert derive_messages(session) == [partial]


def test_derive_keeps_tool_calls_inside_assistant_message() -> None:
    session = _session()
    call = ToolCallBlock(id="c1", name="echo", arguments='{"text": "x"}')
    assistant = Message(role="assistant", content=(call,))
    session.append("assistant/message", AssistantMessageData(turn=1, step=1, message=assistant))

    derived = derive_messages(session)
    assert derived == [assistant]
    assert derived[0].content == (call,)


def test_unknown_event_types_are_ignored_by_projection() -> None:
    session = _session()
    session.append("experiment/whatever", {"x": 1})
    user = Message(role="user", content=(TextBlock("q"),))
    session.append("user/message", UserMessageData(message=user, source="user"))

    assert derive_messages(session) == [user]


def test_notify_callback_fires_on_append() -> None:
    session = _session()
    seen: list[tuple[str, int]] = []
    session.set_notify(lambda s, e: seen.append((e.type, e.seq)))

    session.append("turn/start", TurnStart(turn=1))

    assert seen == [("turn/start", 0)]


def test_events_of_filters_by_type() -> None:
    session = _session()
    session.append("turn/start", TurnStart(turn=1))
    session.append("step/start", StepStart(turn=1, step=1))
    session.append("step/end", StepEnd(turn=1, step=1))

    assert [e.data.turn for e in session.events_of("turn/start")] == [1]
    assert len(session.events_of("step/start")) == 1
