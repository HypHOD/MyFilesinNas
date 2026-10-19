"""mini-harness：插件式 agent loop 的最小实现（语义对齐 DeepSeek Harness）。

分层（自底向上）：

    container  Context 插件容器（服务注册 / inject 等待 / effect 撤销）
    events     Emitter 三模式事件（emit / waterfall / serial）
    messages   消息与流式分片词汇
    session    SessionEvent 仅追加日志 + derive_messages() 投影
    llm        LlmProvider 协议、BlockAssembler、MockProvider
    tools      ToolRegistry + 三段执行流水线（pre / execute / post）
    agent      Agent 句柄 + Inbox + AgentRegistry（ctx.agents）
    agent_loop 默认驱动器：turn/step 状态机 + 拦截点 + 取消合成

一次 followup 的数据流：

    Context.plugin/activate（container.py）按 inject 激活插件
      → AgentRegistry.create（agent.py）建 Session、接 session/event、启动 loop
      → AgentLoop._run（agent_loop.py）从 inbox 领取消息
      → _run_turn / _run_step：pre-step → 请求模型 →（工具）→ 落日志 → turn/end
      → llm.py 的 provider.stream + BlockAssembler 把分片折叠成 assistant 消息
      → tools.run_tool_pipeline 执行工具，结果以 ToolResultMessage 落日志
      → 下一步请求时 session.derive_messages() 从日志重建历史
"""

from mini_harness.agent import (
    Agent,
    AgentDriver,
    AgentRegistry,
    AgentsPlugin,
    Inbox,
    InboxMessage,
)
from mini_harness.agent_loop import (
    AgentLoop,
    AgentLoopPlugin,
    PreStepEnter,
    PreStepReject,
    RequestErrorRaise,
    RequestErrorRetry,
    RequestSpec,
)
from mini_harness.container import Context, PluginHandle
from mini_harness.events import Emitter
from mini_harness.llm import (
    BlockAssembler,
    GenerateOptions,
    LlmError,
    LlmPlugin,
    LlmProvider,
    LlmService,
    MockProvider,
    ScriptedResponse,
    text_response,
    tool_call_response,
)
from mini_harness.messages import (
    BlockEnd,
    BlockStart,
    Finish,
    Message,
    ModelMessage,
    TextBlock,
    TextDelta,
    ToolCallBlock,
    ToolCallDelta,
    ToolResultMessage,
    message_text,
    text_message,
    tool_calls_of,
)
from mini_harness.session import (
    AssistantMessageData,
    Session,
    SessionEvent,
    StepEnd,
    StepStart,
    ToolCallData,
    ToolResultData,
    TurnEnd,
    TurnStart,
    UserMessageData,
    derive_messages,
)
from mini_harness.tools import (
    PostToolAccept,
    PostToolBlock,
    PreToolAllow,
    PreToolDeny,
    ToolCallView,
    ToolDefinition,
    ToolRegistry,
    ToolsPlugin,
    run_tool_pipeline,
)

__all__ = [
    # 容器与事件
    "Context",
    "PluginHandle",
    "Emitter",
    # 消息与流式分片
    "Message",
    "ModelMessage",
    "TextBlock",
    "ToolCallBlock",
    "ToolResultMessage",
    "text_message",
    "message_text",
    "tool_calls_of",
    "BlockStart",
    "TextDelta",
    "ToolCallDelta",
    "BlockEnd",
    "Finish",
    # 会话
    "Session",
    "SessionEvent",
    "TurnStart",
    "TurnEnd",
    "StepStart",
    "StepEnd",
    "UserMessageData",
    "AssistantMessageData",
    "ToolCallData",
    "ToolResultData",
    "derive_messages",
    # LLM
    "LlmProvider",
    "LlmService",
    "LlmPlugin",
    "LlmError",
    "GenerateOptions",
    "BlockAssembler",
    "MockProvider",
    "ScriptedResponse",
    "text_response",
    "tool_call_response",
    # 工具
    "ToolDefinition",
    "ToolRegistry",
    "ToolsPlugin",
    "ToolCallView",
    "PreToolAllow",
    "PreToolDeny",
    "PostToolAccept",
    "PostToolBlock",
    "run_tool_pipeline",
    # Agent
    "AgentDriver",
    "Agent",
    "Inbox",
    "InboxMessage",
    "AgentRegistry",
    "AgentsPlugin",
    "AgentLoop",
    "AgentLoopPlugin",
    "PreStepEnter",
    "PreStepReject",
    "RequestSpec",
    "RequestErrorRetry",
    "RequestErrorRaise",
]
