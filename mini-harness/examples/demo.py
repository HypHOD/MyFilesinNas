"""mini-harness 端到端演示：两幕脚本化场景。

    幕一  正常工具轮次：read_file 被调用、执行、结果回给模型、模型收尾；
    幕二  guard 拦截：路径穿越被 tools/pre-execute 拒绝，模型看到的只有
          ``Error: ...`` 文本（「模型可见即已记录」）。

全程使用脚本化 MockProvider——无网络、无 key、确定性；运行：``python examples/demo.py``
"""

from __future__ import annotations

import asyncio
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mini_harness.agent import AgentsPlugin
from mini_harness.agent_loop import AgentLoopPlugin
from mini_harness.container import Context
from mini_harness.llm import LlmPlugin, MockProvider, text_response, tool_call_response
from mini_harness.messages import Message, ToolResultMessage, message_text
from mini_harness.session import Session, derive_messages
from plugins.demo_tools import demo_tools_plugin
from plugins.guard_plugin import GuardPlugin
from plugins.logging_plugin import LoggingPlugin


def dump_projection(session: Session) -> None:
    # 演示「模型可见即已记录」：这里打印的正是下一次请求会带上的历史。
    print("\n-- derive_messages()（本次会话的模型历史投影） --")
    for message in derive_messages(session):
        if isinstance(message, ToolResultMessage):
            flag = "error" if message.is_error else "ok"
            print(f"  tool[{flag}] {message.content!r}")
        else:
            role = message.role
            for kind, text in _blocks(message):
                print(f"  {role:<9} {kind}: {text!r}")


def _blocks(message: Message) -> list[tuple[str, str]]:
    parts: list[tuple[str, str]] = []
    for block in message.content:
        if hasattr(block, "text"):
            parts.append(("text", block.text))
        else:
            parts.append(("call", f"{block.name}({block.arguments})"))
    return parts


async def main() -> None:
    workspace = Path(tempfile.mkdtemp(prefix="mini-harness-demo-"))
    (workspace / "hello.txt").write_text("Hello, mini-harness!", encoding="utf-8")

    # 两幕各需要两次模型请求：先要求调工具，再根据工具结果收尾。
    # 脚本按这个顺序排好，MockProvider 每收到一次请求就弹出一条。
    provider = MockProvider(
        script=[
            # 幕一：模型要求读文件 → 拿到结果后总结
            tool_call_response(("read_file", {"path": "hello.txt"})),
            text_response("我读到了：文件内容是 'Hello, mini-harness!'。"),
            # 幕二：模型要求读目录外文件 → 被 guard 拒绝后换说法
            tool_call_response(("read_file", {"path": "../secret.txt"})),
            text_response("读取被 guard 拒绝了，我换一个允许范围内的路径再试。"),
        ]
    )

    ctx = Context()
    # 挂载顺序无关紧要：AgentLoopPlugin 声明 inject=("agents","tools","llm")，
    # 依赖齐了才会被容器激活（见 container._activate_parked）。
    ctx.plugin(LlmPlugin([provider]))          # 提供 ctx.llm
    ctx.plugin(demo_tools_plugin(workspace))   # 提供 ctx.tools（read_file + echo）
    ctx.plugin(GuardPlugin())                  # 拦截 read_file 的路径穿越
    ctx.plugin(LoggingPlugin())                # 打印每条会话事件
    ctx.plugin(AgentsPlugin())                 # 提供 ctx.agents
    ctx.plugin(AgentLoopPlugin())              # 提供默认驱动器
    await ctx.ready()                          # 等所有（依赖已齐的）插件激活完成

    agent = ctx.agents.create(system_prompt="你是演示用助手，需要文件内容时调用 read_file。")
    try:
        print("=" * 72)
        print("幕一：正常工具轮次 —— 用户请模型读 hello.txt")
        print("=" * 72)
        # followup 入 inbox.next_turn 并唤醒 loop；when_idle 等这一轮彻底跑完。
        agent.followup("读一下 hello.txt")
        await agent.when_idle()
        dump_projection(agent.session)

        print("\n" + "=" * 72)
        print("幕二：guard 拦截 —— 用户请模型读 ../secret.txt（目录外）")
        print("=" * 72)
        agent.followup("再读一下 ../secret.txt")
        await agent.when_idle()
        dump_projection(agent.session)

        print("\n-- 会话事件类型序列（两幕累计） --")
        print("  " + ", ".join(event.type for event in agent.session.events))
    finally:
        print("\n-- 卸载容器（logging 插件展示 LIFO 卸载顺序） --")
        # 递归卸载所有插件作用域：停 loop task、摘监听器、注销服务/工具，最后打印 unmounted。
        await ctx.dispose()
        shutil.rmtree(workspace, ignore_errors=True)
    print("done.")


if __name__ == "__main__":
    asyncio.run(main())
