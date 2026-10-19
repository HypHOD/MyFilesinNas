"""存储管理 agent 的终端控制台。

用法：
    cd DemoFile && source .venv/bin/activate
    export DEEPSEEK_API_KEY=sk-...
    python scripts/agent_console.py

可选环境变量：DEEPSEEK_MODEL（默认 deepseek-chat）、DEEPSEEK_BASE_URL（兼容网关）。
命令：:events 重放完整事件序列（append-only 日志），:quit 退出。

身份说明：agent loop 是创建时刻 create_task 起的常驻任务，contextvar 随创建
快照进任务 —— 本脚本在创建 agent 前 set_current_user_id(ADMIN_ID)，工具因此
以管理员身份（用户根 = /）执行。嵌入后端时由 HTTP 入口按登录用户设置同一处。
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 先导入 app.agent 包：其 __init__ 会为未安装的 mini-harness 兜底 sys.path，
# 下面直接 import mini_harness 才成立。
from app.agent.host import SYSTEM_PROMPT, build_context
from app.agent.provider import DeepSeekProvider
from app.core.context import set_current_user_id
from app.models.user import ADMIN_ID
from app.storage import registry
from app.storage.loader import load_storage_sources
from mini_harness.agent import Agent
from mini_harness.messages import message_text
from mini_harness.session import (
    AssistantMessageData,
    Session,
    SessionEvent,
    ToolCallData,
    ToolResultData,
    TurnEnd,
)

HELP = "输入消息开始对话；:events 重放事件序列，:quit 退出。"


def _on_session_event(_session: Session, event: SessionEvent) -> None:
    """session/event 实时打印（sync 监听器 → emit 直接内联调用）。"""
    data = event.data
    if event.type == "assistant/message":
        assert isinstance(data, AssistantMessageData)
        text = message_text(data.message)
        suffix = "（回答被中断）" if data.interrupted else ""
        print(f"\n助手 > {text}{suffix}")
    elif event.type == "tool/call":
        assert isinstance(data, ToolCallData)
        args = data.arguments if len(data.arguments) <= 160 else data.arguments[:160] + "…"
        print(f"  [调用] {data.name} {args}")
    elif event.type == "tool/result":
        assert isinstance(data, ToolResultData)
        content = data.message.content.replace("\n", " / ")
        if len(content) > 200:
            content = content[:200] + "…"
        tag = "错误" if data.message.is_error else "结果"
        print(f"  [{tag}] {content}")
    elif event.type == "turn/end":
        assert isinstance(data, TurnEnd)
        if data.status != "completed":
            print(f"[轮次 {data.turn} 结束: {data.status}]")


def _dump_events(session: Session) -> None:
    print("-- 事件序列（append-only 日志；模型可见即已记录） --")
    for event in session.events:
        data = event.data
        if event.type == "assistant/message":
            text = message_text(data.message).replace("\n", " ")
            print(f"{event.seq:>3} {event.type:<18} {text[:100]}")
        elif event.type == "user/message":
            print(f"{event.seq:>3} {event.type:<18} {message_text(data.message)[:100]}")
        elif event.type == "tool/call":
            print(f"{event.seq:>3} {event.type:<18} {data.name} {data.arguments[:100]}")
        elif event.type == "tool/result":
            tag = "错误" if data.message.is_error else "ok"
            print(f"{event.seq:>3} {event.type:<18} {tag}: {data.message.content[:80]!r}")
        elif event.type == "turn/end":
            print(f"{event.seq:>3} {event.type:<18} turn={data.turn} status={data.status}")
        else:  # turn/start、step/start、step/end、system/message
            print(f"{event.seq:>3} {event.type}")


async def _repl(agent: Agent) -> None:
    while True:
        try:
            line = (await asyncio.to_thread(input, "\n你 > ")).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not line:
            continue
        if line in {":q", ":quit", ":exit"}:
            return
        if line == ":events":
            _dump_events(agent.session)
            continue
        agent.followup(line)
        await agent.when_idle()
        if agent.last_error is not None:
            print(f"[轮次错误] {type(agent.last_error).__name__}: {agent.last_error}")
            agent.last_error = None


async def _main(provider: DeepSeekProvider) -> None:
    set_current_user_id(ADMIN_ID)  # 必须在创建 agent 之前设置：loop task 会继承当前 context 快照

    print("装载存储源…")
    load_storage_sources()  # 与后端 lifespan 同一个装配口
    services = registry.all_services()
    if services:
        keys = "、".join(sorted(s.storage_key or "?" for s in services.values()))
        print(f"存储源 {len(services)} 个：{keys}")
    else:
        print("[警告] 注册表为空 —— 先跑 python scripts/seed_local_storage.py（新库还需先 init_db.py）")

    ctx = await build_context(provider)
    ctx.on("session/event", _on_session_event)
    agent = ctx.agents.create(
        system_prompt=SYSTEM_PROMPT,
        provider=provider.name,
        model=provider.model,
    )
    print(f"模型：{provider.model}（provider={provider.name}）")
    print(HELP)
    try:
        await _repl(agent)
    finally:
        await ctx.dispose()
        print("已退出。")


def main() -> None:
    try:
        provider = DeepSeekProvider()
    except ValueError as exc:
        print(f"[配置] {exc}")
        print("用法：export DEEPSEEK_API_KEY=sk-xxx && python scripts/agent_console.py")
        raise SystemExit(2) from None
    asyncio.run(_main(provider))


if __name__ == "__main__":
    main()
