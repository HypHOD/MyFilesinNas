# mini-harness

用 Python（3.11+，运行时零依赖）从零实现的**迷你版插件式 agent loop**，模仿
[DeepSeek Harness (dsh)](https://github.com/deepseek-ai) 的精髓机制：

- 插件容器（服务注册、`inject` 依赖等待、注册即可逆副作用）；
- 三模式事件（`emit` 观察 / `waterfall` 拦截 / `serial` 终结检查）；
- 仅追加的会话日志 + 「模型可见即已记录」的纯投影；
- 三段工具流水线（pre / execute / post）与并行分类；
- Agent 句柄 + inbox（followup / steer / inject / cancel）与 turn/step 状态机。

这是一个**学习与面试向**的项目：结构对照 dsh 逐模块直译，砍掉一切非必要复杂度
（见文末差异表）。无网络、无 API key、确定性可测。

## 30 秒跑起来

```bash
cd mini-harness

python3 examples/demo.py          # 两幕演示：正常工具轮次 + guard 拦截
python3 -m pytest tests/ -q       # 50 个用例，约 0.05s
```

> 要求 Python ≥ 3.11（开发于 3.13）。测试不依赖 pytest-asyncio——`tests/conftest.py`
> 里的 `run_async` 装饰器用 `asyncio.run` 包一层，保持零依赖。

demo 输出（节选）：

```
幕一：正常工具轮次 —— 用户请模型读 hello.txt
[logging] turn/start #0
[logging] system/message #1
[logging] user/message #2
[logging] step/start #3
[logging] assistant/message #4     ← 模型要求调用 read_file
[logging] tool/call #5
[logging] tool/result #6
...
  assistant call: 'read_file({"path": "hello.txt"})'
  tool[ok] 'Hello, mini-harness!'

幕二：guard 拦截 —— 用户请模型读 ../secret.txt（目录外）
  tool[error] "Error: guard: path '../secret.txt' looks like a traversal"
  assistant text: '读取被 guard 拒绝了，我换一个允许范围内的路径再试。'
```

## 一个 turn 里发生了什么

```
agent.followup("…")   agent.steer("…")  agent.inject("…")
        │ 排入 inbox.next_turn（唤醒） │ 排入 next_step（唤醒）│ 排入 next_step（不唤醒）
        ▼
┌─ loop task（常驻）───────────────────────────────┐   ┌─ 会话日志（仅追加）─┐
│ turn/start                                       │──▶ turn/start
│ agent/pre-step  waterfall: enter | reject        │
│ user/message（首个 turn 前先落 system/message）  │──▶ user/message
│ ┌ step/start ────────────────────────────────┐   │──▶ step/start
│ │ agent/request  waterfall（可改写 provider） │   │
│ │ derive_messages() + tools.schemas()        │   │   「模型可见即已记录」：
│ │ provider.stream() → BlockAssembler 折叠    │   │    请求内容全部来自日志投影
│ │ assistant/message                          │   │──▶ assistant/message
│ │ 工具调用：全部先按模型序落盘                │   │──▶ tool/call
│ │   独占屏障逐个 / 并发安全段走有界并行池     │   │
│ │   结果按模型序提交（失败=Error 文本不终止） │   │──▶ tool/result
│ └ step/end ───────────────────────────────────┘   │──▶ step/end
│ 有工具调用或有新 steer → 下一 step                │
│ 否则 agent/turn-stopping（serial）→ 无新输入收口  │
└ turn/end                                          │──▶ turn/end（completed/canceled/error）
```

取消（`agent.cancel()`）：已到达的文本前缀落 `assistant/message(interrupted)`，
未提交的工具调用补合成结果（已开工 = outcome unknown，未派发 = aborted before
dispatch）——日志里每个 `tool/call` 必有对应 `tool/result`。

## 模块依赖图

```
container ─────────────▶ events          Context 插件容器 / Emitter 三模式事件
messages（独立）                         消息与流式分片词汇
session ───────────────▶ messages        仅追加日志 + derive_messages() 投影
llm ───────────────────▶ events, messages      提供方协议 / BlockAssembler / Mock
tools ─────────────────▶ container, events, messages   注册表 + 三段执行流水线
agent ─────────────────▶ container, events, session    句柄 / Inbox / 注册表
agent_loop ────────────▶ agent, container, llm, messages, session, tools
                         默认驱动器：turn/step 状态机、拦截点、取消合成

plugins/* ──▶ mini_harness   扩展示范（工具、观察、拦截三种模式）
examples/demo.py ──▶ 全部    装配 + 两幕场景
```

每个模块的 docstring 都标注了对应的 dsh 源码对照点：

| mini 模块 | dsh 对照 |
|---|---|
| `container.py` | Cordis 容器（`vendor/cordis`，docs/cordis-primer.zh.md） |
| `events.py` | `vendor/cordis/src/events.ts` 三模式语义权威 |
| `session.py` | `packages/core/session/src/surface.ts` deriveEventMessage |
| `llm.py` | `packages/llm/llm/src/assembler.ts` 分片折叠 |
| `tools.py` | `packages/core/tools` 流水线 |
| `agent.py` | `packages/core/agent/src/runtime-types.ts` |
| `agent_loop.py` | `packages/core/agent-loop/src/agent.ts`、`tool-calls.ts` |

## 核心机制导览

**1. 插件容器（container.py）**。Context 是服务容器：`ctx.provide("x", svc)`
占稳定键，`ctx.x` 经 `__getattr__` 代理读取。插件声明 `inject = ("agents",…)`，
依赖未齐时挂起，每次 `provide` 后自动重查并激活就绪者。一切注册返回 disposer，
`ctx.effect()/ctx.on()` 记入插件作用域（子 Context）的副作用栈，卸载与
`ctx.dispose()` 按 LIFO 撤销。

**2. 三模式事件（events.py）**。`emit` 广播不等待；`waterfall` 是环绕中间件——
监听器签名 `(*args, next)`，调用 `await next()` 委托下游，不调即为**短路拦截**
（`next()` 不带参沿用当前参数，带参则替换）；`serial` 按序 await 收集返回值，
用于 `agent/turn-stopping` 这类终结检查点。

**3. 会话日志与投影（session.py）**。`SessionEvent{type, seq, time, data}` 仅追加，
seq 单调。核心不变式：任何到达模型请求的内容都必须能从 `derive_messages()`
重建——user 消息、非空 assistant 消息、tool result 是 surface；turn/step 边界与
`tool/call`（已在 assistant 消息里）不投影。

**4. LLM seam（llm.py）**。提供方最小形状 `stream(options) -> AsyncIterator[chunk]`，
一次调用一次尝试、库内不重试（重试属于 agent_loop 的 `agent/request-error`）。
`BlockAssembler` 按 index 槽位把分片折叠回消息；`max_tokens` 截断时丢弃全部
工具调用（参数不完整不可执行）。`MockProvider` 按脚本演出，耗尽抛
`LlmError("SCRIPT_EXHAUSTED")`。

**5. 工具流水线（tools.py）**。每次调用三段 waterfall：`tools/pre-execute`
（`PreToolAllow | PreToolDeny`，deny 单调不可翻回）→ `tools/execute`（环绕真实
执行，异常转 `ToolRunFailure`）→ `tools/post-execute`（`PostToolAccept | PostToolBlock`
可改写/推翻结果）。失败是进模型历史的 `Error: ...` 文本，**不终止轮次**。
`is_concurrency_safe` 显式声明的连续调用才并行；其余独占屏障。

**6. Agent 句柄与 inbox（agent.py）**。`followup` 排下一轮并唤醒；`steer` 排下一步
并唤醒（loop 空闲时开启新轮）；`inject` 排下一步但不唤醒。`cancel(keep_inbox=…)`
中止当前工作而不终止 loop；`when_idle()` 等到没活干且 inbox 空。loop task 是
inbox 的唯一消费者。

**7. 默认驱动器（agent_loop.py）**。拦截点：`agent/pre-step`（决定本轮输入是否
入账）、`agent/request`（改写 provider/model）、`agent/request-error`（返回
`RequestErrorRetry()` 重试同一 step，或 `await next()` 上抛为轮次错误）。
turn 错误只终结该轮：`turn/end(status="error")` + `agent.last_error`，loop 继续
服务后续 followup。

## 扩展指南：写你自己的插件

插件 = 一个带 `name` / `inject` / `apply(ctx)` 的对象（也可以直接是函数）。
按用途选注册方式：

| 想做的事 | 用什么 | 参考 |
|---|---|---|
| 提供一种能力（工具、服务） | `ctx.provide()` / `ctx.effect()` | `plugins/demo_tools.py` |
| 观察不改写 | `ctx.on("session/event", …)` 或 waterfall 里 `await next()` | `plugins/logging_plugin.py` |
| 拦截改写 | waterfall 里直接返回决策对象（短路） | `plugins/guard_plugin.py` |

完整模板（计数每次工具调用，超限即拦截）：

```python
from mini_harness.tools import PreToolDeny

class ToolBudgetPlugin:
    name = "tool-budget"
    inject = ("tools",)          # 等 ctx.tools 就绪才激活

    def __init__(self, limit: int = 3) -> None:
        self._limit = limit

    def apply(self, ctx) -> None:
        used = 0

        async def budget(view, next):          # waterfall：(*args, next)
            nonlocal used
            used += 1
            if used > self._limit:
                return PreToolDeny(reason=f"tool budget exhausted ({self._limit})")
            return await next()                # 委托下游；不调 next() 即短路

        ctx.on("tools/pre-execute", budget)

# 装配：排在其他插件之后、await ctx.ready() 之前
ctx.plugin(ToolBudgetPlugin(limit=5))
```

挂载后无需其他接线：拦截立即生效，监听器随插件卸载自动撤销（LIFO）。

## 与 dsh 的差异（有意砍掉的机制）

| 方面 | dsh | mini 版 | 为什么砍 |
|---|---|---|---|
| 持久化 | JSONL 落盘、版本迁移、resume/fork、崩溃修复 | Session 纯内存 | 迷你版聚焦机制而非运维；仅保留「未启动调用补合成失败结果」的调度正确性 |
| 请求组装 | request/header、systemPrompt sections/variables、runtime-context | 每步现拼 `derive_messages()` + `tools.schemas()` | 减少一层间接；约定运行期不变更工具注册表 |
| LLM 层 | prepareCall、多适配器路由、usage 计量、reasoning/图片块、llm-retry | 按 name 查提供方；保留 `NO_PROVIDER`/`SCRIPT_EXHAUSTED` 错误码 | 错误码与重试点（`agent/request-error`）已覆盖教学所需 |
| 工具层 | 审批(ask)、sandbox、结果 schema 校验、concludeTurn | allow/deny 与 accept/block 两类决策 | 决策联合的形状保留了，扩展点齐全 |
| 事件 | 同步 emit、scope 过滤分发、并行模式 | async emit（后台任务 + `drain()`）、无 scope 过滤 | Python 习惯；`drain()` 让测试保持确定性 |
| 平台 | subagent、Loader/cordis.yml、HMR、settings/telemetry、SDK/wire | 全砍 | README 即学习边界；这些是「想进一步模仿」的方向 |
| 测试 | vitest | pytest + 自写 `run_async`（`asyncio.run` 包装） | 不引入 pytest-asyncio，保持运行时/测试零第三方依赖 |

已知的简化边界（有意为之，不是 bug）：

- `emit` 的同步监听器抛错会向上穿透——观察者被信任，不做错误隔离；
- 运行期不支持热插拔工具（每次请求现场投影注册表，稳定性由约定保证）；
- `agent/request-error` 的重试次数不限，由监听器自行把关（dsh 有预算机制）。

## 目录结构

```
mini-harness/
├── mini_harness/          核心包（按依赖方向分层，见上方模块图）
│   ├── container.py       Context：服务/注入/副作用/插件挂载
│   ├── events.py          Emitter：emit / waterfall / serial
│   ├── messages.py        消息与流式分片
│   ├── session.py         SessionEvent 日志 + derive_messages()
│   ├── llm.py             提供方协议 / BlockAssembler / MockProvider
│   ├── tools.py           ToolRegistry + 三段流水线
│   ├── agent.py           Agent / Inbox / AgentRegistry（ctx.agents）
│   └── agent_loop.py      默认驱动器 + 拦截点决策
├── plugins/               扩展示范
│   ├── demo_tools.py      注册 read_file（目录限制）+ echo
│   ├── logging_plugin.py  session/event 观察 + pre-step 透传
│   └── guard_plugin.py    拒绝路径穿越（waterfall 短路）
├── examples/demo.py       两幕组装演示
└── tests/                 50 个用例（events 10 / session 8 / tools 15 / loop 17）
```
