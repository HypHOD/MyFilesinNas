"""示例插件：生命周期日志。

两种观察方式：

- emit 观察：监听 ``session/event``，打印任何进入会话日志的事件
  （turn/step 边界、消息、工具调用与结果）；
- waterfall 透传：监听 ``agent/pre-step`` 并调用 ``next()`` 委托下游，只观察
  不改写；直接返回 PreStepReject 则变为拦截器（对照 guard_plugin）。

unload 消息的副作用最先注册，按 LIFO 最后执行：先摘监听器，再打印卸载完成。
"""

from __future__ import annotations

from typing import Any

from mini_harness.container import Context
from mini_harness.session import SessionEvent


class LoggingPlugin:
    """把会话与 agent 生命周期打印到 stdout。"""

    name = "logging"

    def __init__(self) -> None:
        self._lines: list[str] = []

    def apply(self, ctx: Context) -> None:
        # 卸载消息的副作用最先注册，按 LIFO 会最后执行：
        # 先由其他 disposer 摘掉监听器，再打印 unmounted。
        ctx.effect(lambda: print("[logging] unmounted"))

        def on_session_event(session: Any, event: SessionEvent) -> None:
            # 纯观察：session 每次 append 都会广播到这里，不改任何行为。
            line = f"[logging] {event.type} #{event.seq}"
            self._lines.append(line)
            print(line)

        ctx.on("session/event", on_session_event)

        async def observe_pre_step(agent: Any, messages: tuple, next: Any) -> Any:
            # 调用 next() 表示只观察不改写；直接返回 PreStepReject 则变为拦截器。
            print(f"[logging] pre-step claimed {len(messages)} message(s)")
            return await next()

        ctx.on("agent/pre-step", observe_pre_step)

    @property
    def lines(self) -> tuple[str, ...]:
        return tuple(self._lines)
