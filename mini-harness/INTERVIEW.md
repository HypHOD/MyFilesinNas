# mini-harness 面试准备手册

> 用途：项目展示、白板讲解、追问防守。
> 代码基线：`main @ 4627307`，agent 接入提交 `b875b3b`。
> 核心原则：**只讲你真做过、能落到代码的细节**；边界和取舍主动说，比被问出来更加分。

---

## 0. 先记住这 8 个数字

| 数字 | 含义 |
|---|---|
| **1,766 行** | 核心 8 个模块（container / events / messages / session / llm / tools / agent / agent_loop），不含导出与测试 |
| **0** | 核心运行时第三方依赖（Python ≥ 3.11；HTTP 等依赖都在接入层） |
| **50 个** | mini-harness 确定性单测，`pytest` 约 0.05s 跑完 |
| **7 个** | 核心机制：插件容器、三模式事件、仅追加日志、LLM seam、工具流水线、Agent/Inbox、默认驱动器 |
| **5 个** | 接入 DemoFile 的存储工具：`list_storage_sources` / `list_files` / `file_info` / `new_folder` / `rename` |
| **7 个** | `/api/agent` HTTP 端点（建会话、列表、状态、发消息、取消、删除、SSE） |
| **15 秒** | SSE 空闲心跳（`: ping`）间隔 |
| **+1,748 行 / 20 文件** | `b875b3b` 一次接入提交的规模（含 Vue 前端） |

补充：DemoFile 后端测试 **78 个全过**（`.venv` 下 0.34s）。

---

## 1. 项目介绍逐字稿

### 1.1 一句话版本

> 我用 Python 从零实现了一个零运行时依赖的插件式 Agent Harness，并把它接进自己的 NAS 全栈项目，实现了用自然语言做存储管理。

### 1.2 30 秒版本

> 我的个人项目 MyFilesinNas 是一个 NAS / 番剧站点。路线图里有一项是「agent 接入做存储管理」，我没有直接套 LangChain，而是先写了一个 mini-harness：核心约 1,800 行，包含插件容器、三模式事件总线、仅追加会话日志、流式 LLM 适配、工具三段流水线、Agent inbox 和 turn/step 状态机。
>
> 之后我把它接到真实后端：DeepSeek 流式 provider、5 个存储工具、7 个 HTTP/SSE 接口和 Vue 前端。用户可以问「列出所有存储源」「在 Bangumi 下建个文件夹」，模型会真实调工具。
>
> 项目有 50 个确定性单测，0.05 秒跑完。我想展示的重点不是「会调模型 API」，而是对 agent loop 内部机制、取消一致性、并发调度和流式协议的理解。

### 1.3 2 分钟版本

> 面试官您好，我介绍 mini-harness。它是我在个人 NAS 项目 MyFilesinNas 里做的一个 agent 基础设施。
>
> **背景**：这个站点有文件浏览、RSS 自动下载、qBittorrent 和对外剧集页。我希望用户能用自然语言管理存储，比如查目录、建文件夹、重命名。调研之后我发现，直接上 LangChain 这类框架当然快，但 loop、流式拼接、工具调度、取消这些最容易出错的细节都被封装掉了，出了线上问题很难定位。所以我的策略是：先从一个生产级 harness（DeepSeek Harness，dsh）的架构里学习，用 Python 从零实现一个最小版本，把它吃透，再接入真实业务。
>
> **实现**：核心分 8 层，自底向上是插件容器、事件总线、消息词汇、会话日志、LLM seam、工具系统、Agent 句柄、默认驱动器。几个关键设计：
>
> 第一，**仅追加会话日志 + 投影**。所有模型能看见的内容都必须能从日志重建，也就是「模型可见即已记录」。这带来三个好处：历史可重放、SSE 可以直接从日志按 seq 重放、取消时日志仍然自洽。
>
> 第二，**三模式事件**。`emit` 只观察，`waterfall` 是可短路的洋葱中间件，`serial` 是顺序收集意见的终结检查点。工具准入、请求改写、错误重试都挂在这些拦截点上。
>
> 第三，**工具流水线 + 并发调度**。每次调用走 pre / execute / post 三段；默认独占，只有显式声明并发安全的连续工具才走有界并行池，结果仍按模型调用顺序提交。
>
> 第四，**取消一致性**。取消不是简单抛异常：已到达的文本前缀会落一条 interrupted 消息；已开工的工具补「outcome unknown」，未派发的补「aborted before dispatch」，保证每个 `tool/call` 都有配对的 `tool/result`。
>
> **接入**：后端用 DeepSeek 的 OpenAI 兼容流式接口，实现了 provider 协议；暴露 7 个 `/api/agent` 端点，回答和工具轨迹走 SSE。前端是 Vue 的浮动按钮加右侧抽屉，自己实现了 EventSource 重连、seq 去重和乐观气泡。身份通过 contextvar 在创建 agent 时快照进常驻 loop 任务，工具因此总是以会话属主的权限执行。
>
> **结果**：核心 50 个测试 0.05 秒跑完，DemoFile 78 个后端测试全过；接入层 20 个文件约 1,750 行。
>
> **边界**：会话是纯内存的，重启即失效；没有上下文压缩、没有沙箱和人工审批；删除/移动/复制这些破坏性工具我故意没开，等权限模型接进工具层再说。这些是我明确划的学习边界，不是没意识到。

### 1.4 5 分钟白板路线

按这个顺序画，边画边讲：

1. **画分层**：`container/events → messages → session → llm → tools → agent → agent_loop`。
2. **画一次 turn**：`followup → inbox → turn/start → pre-step → step/start → 请求模型 → assistant/message → tool/call → tool/result → 下一 step 或 turn/end`。
3. **画取消分支**：在流式中间和工具执行中间各画一刀，说明两类合成结果。
4. **画接入边界**：左边 mini-harness（协议、日志），右边 DemoFile（provider、工具、SSE、鉴权）、前端。
5. **收尾讲取舍**：为什么内存、为什么单进程、为什么不做破坏性工具、下一步怎么做。

---

## 2. 项目定位与背景

### 2.1 项目是什么

- **mini-harness**：一个模仿 DeepSeek Harness 的迷你插件式 agent loop，定位是「学习与面试向」，但代码按可测试、可扩展的方式写，不是玩具脚本。
- **MyFilesinNas**：个人 NAS / 番剧站点，包含文件存储抽象、RSS 订阅与自动下载、qBittorrent、对外剧集页、Docker 部署。
- **两者的关系**：mini-harness 是独立的零依赖包；`DemoFile/app/agent/` 是接入层，负责真实模型、存储工具、HTTP/SSE 和用户身份。

### 2.2 为什么做

1. 业务上：路线图第 3 条是「agent 接入做存储管理」，后续还想用 LLM 升级 RSS 解析。
2. 技术上：想真正理解 agent loop，而不是停留在「调 API + 拼 prompt」。
3. 工程上：框架封装了流式拼接、工具调度、取消、重试这些最容易出错的细节；自研可以让每个不变量都可验证。

### 2.3 有意不做的部分

| 没做 | 原因 |
|---|---|
| JSONL 持久化 / resume / fork | 迷你版聚焦机制；接入层会话重启即失效是预期 |
| 子 agent、Loader/HMR、配置化装配 | 平台层能力，与理解 loop 无关 |
| 工具审批（ask）、sandbox、结果 schema 校验 | 保留决策联合形状，扩展点齐全，但当前不装 |
| 上下文压缩 / surface replace | 日志结构已支持新增事件，压缩是下一步 |
| 多进程 / 分布式会话 | 当前是单进程个人站；扩展路径见 Q&A |

---

## 3. 架构总览

### 3.1 分层

```text
container   Context 插件容器：服务注册 / inject 等待 / effect 撤销
events      Emitter 三模式事件：emit / waterfall / serial
messages    消息与流式分片词汇（纯数据）
session     仅追加日志 + derive_messages() 投影
llm         LlmProvider 协议 / BlockAssembler / MockProvider
tools       ToolRegistry + pre / execute / post 三段流水线
agent       Agent 句柄 / Inbox / AgentRegistry
agent_loop  默认驱动器：turn/step 状态机 + 拦截点 + 取消合成
```

依赖方向严格向下，`messages` 独立无依赖。

### 3.2 一次请求的数据流

```text
AgentLoop._run
  └─ _run_turn                     turn/start
       └─ _run_step                step/start
            └─ _generate
                 ├─ agent/request（可改写 provider/model）
                 ├─ derive_messages(session) + tools.schemas()
                 ├─ provider.stream() → BlockAssembler 折叠
                 └─ assistant/message 落盘
            └─ _run_tool_calls
                 ├─ 先按模型序落全部 tool/call
                 ├─ 独占屏障 / 连续安全工具有界并行
                 └─ 按模型序提交 tool/result
       └─ step/end
       └─ 有工具调用 → 下一 step；否则 agent/turn-stopping → turn/end
```

### 3.3 接入层结构

| 文件 | 职责 |
|---|---|
| `DemoFile/app/agent/provider.py` | DeepSeek 流式 provider：OpenAI 兼容 SSE → `StreamChunk` |
| `DemoFile/app/agent/storage_tools.py` | 5 个存储工具，包装既有 service 层，不新增行为 |
| `DemoFile/app/agent/host.py` | `build_context` 装配 + `AgentHost` 生命周期 / 归属校验 / SSE 流 |
| `DemoFile/app/agent/serialize.py` | session 事件 → camelCase JSON → SSE 帧 |
| `DemoFile/app/modules/agent/router.py` | 7 个 HTTP 端点，登录与归属校验 |
| `DemoFile/app/main.py` | lifespan 启停 agent_host，挂 `/api` 前缀 |
| `mini-harness/scripts/agent_console.py` | Phase C 的 CLI 控制台，调 provider + 工具 |
| `MFN-vue/src/composables/agent/useAgentChat.js` | 模块级单例状态、EventSource 重连、seq 去重 |
| `MFN-vue/src/components/agent/AgentAssistant.vue` | FAB + 非模态抽屉、工具卡、停止/新对话 |

---

## 4. 七个核心机制（主讲点）

### 4.1 插件容器（`container.py`）

**做什么**：`Context` 是服务容器。插件用 `inject = ("agents", "tools", "llm")` 声明依赖；依赖不齐时挂起，任何一次 `provide` 都会触发重新扫描，依赖齐了就自动激活。

**关键实现**：
- `ctx.provide(name, service)` 占稳定键，返回 disposer，并立即 `_activate_parked()`（`container.py:103`）。
- 每个插件激活时拿一个**子 Context**，插件里的 `provide` / `on` / `effect` 都记在子作用域，卸载时只撤销自己的东西。
- 所有注册都是可逆副作用：`effect()` 记入栈，`dispose()` 按 **LIFO** 撤销（`container.py:141`）。
- `ctx.x` 通过 `__getattr__` 代理读取根服务表；找不到显式报错。

**为什么**：装配顺序无关、扩展即插即用、卸载不留悬空监听器。demo 里 `AgentLoopPlugin` 能「等」到三个服务就绪，就是这套机制。

**边界**：没有 scope 过滤、没有运行期服务消失的级联卸载、没有 HMR；这些是多实例平台能力，迷你版有意砍掉。

### 4.2 三模式事件（`events.py`）

| 模式 | 语义 | 典型用途 |
|---|---|---|
| `emit` | 广播，不等待、不改数据流 | 日志、通知、SSE 唤醒 |
| `waterfall` | 洋葱中间件，`listener(*args, next)` | 拦截、改写、短路、重试决策 |
| `serial` | 按注册序 await，收集返回值 | 终结检查点 |

**waterfall 的关键语义**：
- 调 `await next()` → 委托下游并拿到返回值；`next()` 不带参沿用当前参数，带参则替换。
- 不调 `next()` 直接返回 → **短路整条链**，后续监听器和 default 都不执行。
- 例：`guard_plugin` 命中路径穿越时直接返回 `PreToolDeny`，工具执行被整段跳过。

**emit 的简化**：协程监听器被调度为后台任务，`drain()` 统一等待并重抛异常。同步监听器抛错会向上穿透（观察者被信任，不做错误隔离）——这是已知简化。

### 4.3 仅追加日志与投影（`session.py`）

**数据结构**：`SessionEvent{type, seq, time, data}`，seq 单调递增，`append` 是唯一写入口。

**核心不变式**：「任何到达模型请求的内容，都必须能从 `derive_messages()` 重建。」

投影规则：
- `system/message` → 原样进入历史（只写一次）
- `user/message` → 取 `message`
- `assistant/message` → 仅当内容非空
- `tool/result` → 取 `ToolResultMessage`
- `turn/step` 边界、`tool/call` → 不投影（工具调用已经包含在 assistant 消息的块里）

**为什么不用一个可变 messages 数组**：
1. 日志是事实之源，历史是纯函数投影，可重放、可调试、可审计。
2. SSE 重放直接复用同一份 seq，不需要另建消息状态。
3. 取消/出错时日志仍然自洽，不会出现「消息数组改了一半」的状态。

**代价**：日志只增不减，长会话会膨胀；当前没有压缩，属于明确的下一步。

### 4.4 LLM seam 与流式折叠（`llm.py`）

**提供方协议**：`stream(options) -> AsyncIterator[StreamChunk]`。一次调用 = 一次提供方尝试，**库内不重试**；失败抛 `LlmError(code)`，重试由 `agent/request-error` 监听器决定。

**BlockAssembler**：
- 按 `index` 槽位折叠分片；文本槽固定 0，工具调用占 1 + OpenAI 的 `tool_calls[].index`。
- 工具参数**全程保持原始 JSON 字符串**，只做字符串拼接，执行前才解析。
- `max_tokens` 截断时丢弃全部工具调用（参数不完整，不可安全执行）。
- 流结束但没见到 `finish_reason` → `STREAM_TRUNCATED`。
- 同时维护 `delivered_text`，取消时用来落 interrupted 前缀。

### 4.5 工具流水线（`tools.py`）

每次调用三段 waterfall：

```text
tools/pre-execute   → PreToolAllow | PreToolDeny（deny 单调，不可翻回）
tools/execute       → 环绕真实执行，异常转 ToolRunFailure
tools/post-execute  → PostToolAccept（可改写）| PostToolBlock（可推翻）
```

**关键规则**：
- 参数 JSON 非法 → `INVALID_ARGS`；工具不存在 → `UNKNOWN_TOOL`。都不抛异常，转成模型可见的 `Error: ...`。
- 工具失败不终止轮次：错误以文本进入历史，模型可以自行纠正。
- `schemas()` 只导出 `name/description/parameters`，`execute` 绝不发给模型。
- `is_concurrency_safe` 默认 `False`；只有显式声明的连续调用才并行。

### 4.6 Agent 句柄与 inbox（`agent.py`）

| 方法 | 队列 | 是否唤醒 | 语义 |
|---|---|---|---|
| `followup` | `next_turn` | 是 | 排下一轮；当前 turn 结束后处理 |
| `steer` | `next_step` | 是 | 当前 step 结束后立刻插队；空闲时开启新轮 |
| `inject` | `next_step` | 否 | 静默注入，下一次唤醒顺带领取 |
| `cancel` | - | - | 中止当前工作，loop 不退出；默认清空 inbox |

- loop task 是 inbox 的唯一消费者。
- `when_idle()` 等到「没有进行中的工作且 inbox 为空」，是测试和 CLI 的同步点。
- `cancel(keep_inbox=True)` 保留队列，调用方可以马上重试。

### 4.7 默认驱动器（`agent_loop.py`）

**状态机**：
- 一次 `followup` = 一个 turn；turn 内含若干 step。
- step 产出工具调用或有新输入 → 继续下一 step；否则过 `agent/turn-stopping` 后收口。
- 拦截点：`agent/pre-step`（输入是否入账）、`agent/request`（改写 provider/model）、`agent/request-error`（重试或上抛）。

**工具调度**：
- 先按模型顺序把全部 `tool/call` 落盘，保证取消时也有完整调用记录。
- 从左到右：独占工具构成屏障；连续的安全工具合并为一批，走有界并行池（信号量，默认上限 10）。
- `asyncio.gather` 保持批次内模型顺序，提交点逐个按序落 `tool/result`。

**取消合成**：
- 已到达但未完成流式的文本 → 一条 `assistant/message(interrupted=True)`，保留用户看到的前缀。
- 已开工但未提交的工具 → `outcome unknown`；未派发的 → `aborted before dispatch`。
- 保证每个 `tool/call` 都有对应的 `tool/result`，日志永远可投影。

**错误处理**：
- 轮次错误只终结该轮：`turn/end(status="error")` + `agent.last_error`，loop 继续服务后续 followup。
- `agent/request-error` 默认上抛；监听器返回 `RequestErrorRetry` 可重试同一 step。
- 当前没有重试预算，由监听器自行把关（这是有意简化）。

---

## 5. 接入层的关键设计

### 5.1 DeepSeek provider

- 用 `httpx.AsyncClient` 直接打 OpenAI 兼容的 `/chat/completions`，逐行解析 `data:`。
- 文本固定槽 0；工具调用槽 1 + `tool_calls[].index`。
- `finish_reason` 映射：`stop→stop`、`tool_calls→tool_calls`、`length→max_tokens`、`content_filter→error`；未知值直接 `PROVIDER_ERROR`。
- HTTP 非 200 → `HTTP_xxx`；网络异常 → `NETWORK_ERROR`；流结束无 finish → `STREAM_TRUNCATED`。
- 反向转换时，assistant 的 `ToolCallBlock` 还原成 `tool_calls[]`，`ToolResultMessage` 转成 `role=tool` + `tool_call_id`。

### 5.2 存储工具与身份

- 工具入参与 service 层「相对入参族」一致：**相对用户根**（`/`、`/Bangumi`）。
- 用户身份来自 `app.core.context` 的 contextvar。
- **关键约束**：agent loop 是创建时 `create_task` 起的常驻任务，contextvar 随创建时刻快照进任务。因此 `AgentHost.create()` 在创建前显式 `set_current_user_id(user_id)`，让「工具以会话属主身份执行」不依赖上层调用点。
- 阻塞的文件 IO / DB 查询丢进 `asyncio.to_thread`；`to_thread` 会复制当前 context，身份随之进入工作线程。
- 3 个读工具标记 `is_concurrency_safe=True`；2 个写工具保持独占。

### 5.3 SSE 宿主

- `AgentHost.stream()` 维护 `index = max(since + 1, 0)`：先重放历史，再跟随新事件。
- 事件唤醒用每个 agent 一个共享 `asyncio.Event`；`session/event` 到达时 `set()`。
- 空闲 15 秒发 `: ping\n\n` 保活。
- SSE 帧带 `id: seq`、`event: type`、`data: json`；前端可用 `lastEventId` 或 URL `since` 对齐。

**since 语义**：`?since=N` = 已收到的最后 seq，**排他**，从 N+1 开始；默认 `-1` 从头重放。这是对齐 `Last-Event-ID` 的语义。mini-harness 的 seq 是 0 基，如果按包含式默认 0，会吞掉 seq 0——冒烟测试时发现并统一为排他。

### 5.4 前端

- `useAgentChat.js` 是模块级单例：抽屉关闭后状态保留，重开增量续订。
- `EventSource` 原生重连会复用旧 URL（旧 since），不可依赖；`onerror` 时必须 `close()` 并重建 URL。
- 指数退避 1s / 2s / 4s，3 次失败后 `diagnose()`：查会话状态，40400 则新建会话。
- 去重：`seq <= lastSeq` 直接忽略；`lastSeq` 初始 `-1`。
- 乐观气泡：发送时先插入 pending 用户消息；收到 `user/message` 时按文本匹配并转正。
- 工具卡：`assistant/message` 里的 `tool_call` 块和 `tool/call` 事件都走 `upsertToolCall`，避免重复。
- UI 只在文件浏览布局、已登录、非分享/剧集页显示。

---

## 6. 关键决策与取舍

面试官最爱问「为什么这么选」。每个决策都准备「替代方案 + 理由 + 代价」。

| 决策 | 替代方案 | 为什么 | 代价 |
|---|---|---|---|
| 自研 harness | LangChain / LangGraph | 需求简单；想掌握 loop 内部；代码可审计 | 没有生态、持久化、可观测性 |
| 核心零依赖 | 直接用 SDK / pydantic | 确定性测试、可移植、聚焦机制 | 部分能力要自己写 |
| 仅追加日志 | 可变 messages 数组 | 可重放、可审计、取消一致性、SSE 复用 | 长会话膨胀，需要压缩 |
| 默认独占工具 | 全部并行 | 写操作/未知工具不能并发；安全优先 | 并行度低 |
| 库内不重试 | 自动重试 | 重试策略因业务而异，交给拦截点 | 调用方要自己装监听器 |
| SSE | WebSocket | 单向推送、HTTP 友好、自动重连语义 | 客户端消息要走 POST；token 需 query 兜底 |
| 会话内存态 | 落库 / Redis | 个人站、单进程、先跑通 | 重启失效、不能水平扩展 |
| 破坏性工具不开放 | 直接提供 delete/move | 权限模型未接入，不能让模型越权 | 功能不完整 |
| contextvar 身份 | 每次调用显式传 user_id | 与既有 service 层一致，少改接口 | 依赖「创建前 set」的时序约束 |
| 三段决策联合 | 布尔返回值 | 闭联合强制穷举，扩展点清晰 | 代码量更大 |

---

## 7. 高频追问 Q&A

### A. 动机与选型

**A1. 为什么从零写，不用 LangChain / LangGraph？**

> 这个项目需求很窄：单 agent、5 个工具、有明确终止条件。用框架当然更快，但我想搞清楚 loop、流式拼接、工具调度、取消这些细节。自研核心 1,800 行、零依赖，每个不变量都能写测试。代价是生态和持久化要自己做。如果需求扩展到多 agent、复杂 RAG、人工审批，我会重新评估框架，而不是硬扛。

**A2. 这和 dsh 是什么关系？是不是照抄？**

> 架构上是对照 dsh 学的，模块 docstring 里标了对应源码位置。但不是逐行翻译：我用 Python 的 async 语义重写了事件分发，补了取消合成、SSE 接入、真实 provider、存储工具和前端，还写了 50 个测试。差异表在 README 里写得很清楚，哪些砍了、为什么砍。我的目标是理解并落地，不是复制。

**A3. 核心零依赖，生产上够吗？**

> 核心库零依赖是为了可测试和可移植；接入层正常用 FastAPI、httpx、SQLAlchemy、pydantic。生产上我会补结构化日志、指标、持久化，不认为「零依赖」本身是卖点。

**A4. 这个项目最有含金量的点是什么？**

> 不是「会调模型」，而是边界情况：取消时日志仍然自洽；并行工具结果按模型序提交；SSE 断线重放不丢不重；多用户身份在常驻任务和线程池里不串。这些都落到了代码和测试。

**A5. 如果重做一次，你会改什么？**

> 第一，早期就把会话持久化和压缩设计进去，而不是留到后面；第二，把事件 payload 的序列化/版本化统一起来；第三，接入层会更早做真实浏览器验收，而不是只靠 curl 和单测；第四，重试预算、限流和可观测性应该和 loop 一起设计。

### B. 架构与 agent loop

**B1. 一句话解释 agent loop？**

> 一个常驻任务消费 inbox：每个 followup 开一个 turn，turn 内循环 step；每个 step 请求模型、执行工具、把结果落日志，直到模型不再调工具且没有新输入。

**B2. turn 和 step 的区别？**

> turn 是一次用户请求的完整生命周期；step 是一次模型请求 + 它产生的工具调用。模型调了工具就进入下一 step，把工具结果回给模型；不调工具就收口。

**B3. followup / steer / inject 的区别？**

> followup 排下一轮并唤醒；steer 排下一步并唤醒，能在当前 turn 内插队；inject 排下一步但不唤醒，静默补上下文。三者分别对应「新任务」「打断」「旁路信息」。

**B4. 为什么 inbox 要两条队列？**

> 因为轮次边界和步边界语义不同。`next_turn` 每轮只领一条，保证 followup 串行；`next_step` 在 step 结束后全部领走，让 steer/inject 能进入当前 turn。

**B5. loop 为什么常驻，而不是每个请求一个 task？**

> 常驻 loop 让取消只中止当前工作、不销毁 agent；inbox 可以跨轮排队；SSE 也能持续跟随同一份会话日志。每个请求一个 task 会让取消和排队语义复杂很多。

**B6. 三个 agent 拦截点分别做什么？**

> `agent/pre-step` 决定领取的输入是否入账，可以 reject 或改写；`agent/request` 在请求前改写 provider/model；`agent/request-error` 决定重试同一 step 还是上抛为轮次错误。

**B7. turn-stopping 是干什么的？现在真的会阻止收口吗？**

> 它是收口前的终结检查点，`serial` 模式让所有监听器按序表态并收集返回值。当前实现是「收集意见」，返回值没有用来否决收口；真要阻止，可以在监听器里抛错或扩展决策类型。这个我如实说，不夸大。

**B8. 插件容器解决了什么问题？**

> 三件事：服务注册与依赖等待、插件作用域的生命周期、可逆副作用。装配顺序无关，卸载时监听器/工具/服务按 LIFO 撤销，不会留悬空回调。

**B9. inject 是怎么工作的？**

> 插件把自己的依赖名放在 `inject` 元组里。`plugin()` 先入队再尝试激活；每次 `provide()` 都会扫描挂起队列，依赖齐了就创建子 Context 并执行 `apply`。所以 `AgentLoopPlugin` 可以声明依赖三个服务，等它们都就绪再上岗。

**B10. 三种事件模式什么时候用？**

> 只看不改用 `emit`；要拦截、改写、短路用 `waterfall`；要所有监听器按序表态并收集结果用 `serial`。工具准入是 waterfall，turn-stopping 是 serial，日志和 SSE 唤醒是 emit。

### C. 日志与状态

**C1. 为什么用仅追加日志，不直接维护 messages 数组？**

> 日志是事实之源，历史是投影。这样历史可重放、可审计，SSE 可以直接按 seq 重放，取消时也不会出现「数组改了一半」的中间态。代价是长会话膨胀，需要压缩策略。

**C2. 「模型可见即已记录」具体怎么保证？**

> 每次请求的 messages 都来自 `derive_messages(session)`，没有第二条写历史的路径。assistant 消息、工具结果、用户输入都先 append 再投影；工具调用也在 assistant 消息的块里，不会漏记。

**C3. tool/call 不投影，为什么还要记？**

> 三个用途：SSE 给前端展示工具轨迹、取消时给每个调用配对合成结果、调试和审计。它不投影是因为调用信息已经包含在 assistant 消息的 `ToolCallBlock` 里，再投影会重复。

**C4. 日志无限增长怎么办？**

> 当前确实没有压缩，是明确缺口。下一步会加「压缩事件」：把较早的 surface 消息替换成摘要，压缩本身也写进日志，保持可重放；再配合 token 预算和会话 TTL。关键是压缩不能破坏「模型可见即已记录」的不变式。

**C5. seq 怎么生成？并发安全吗？**

> `seq = len(events)`，append 时同步生成。当前所有 append 都在单事件循环里，不需要锁；如果未来多线程写同一会话，要加锁或改成集中写入。

**C6. interrupted assistant 消息为什么要落日志？**

> 取消时用户已经看到了一部分文本。如果不落日志，下一次请求的投影里就没有这段前缀，模型和用户看到的历史会不一致。落一条 `interrupted=True` 的消息，既保留前缀，也标记它是不完整的。

### D. LLM 与流式

**D1. 一次模型请求的完整链路？**

> `agent/request` 决定 provider/model → `derive_messages` 投影历史 → `tools.schemas()` 拿工具白名单 → `provider.stream()` 逐片产出 → `BlockAssembler` 按槽位折叠 → 落 `assistant/message` → 如果有工具调用，进入工具调度。

**D2. 流式分片怎么折叠？为什么按 index？**

> 文本和多个工具调用可能交错到达。按 index 分槽，每个槽独立累积文本或参数；最后按 index 排序还原成内容块。OpenAI 的 `tool_calls[].index` 正好提供这个槽位。

**D3. 工具参数为什么保持字符串？**

> 流式到达时参数是增量拼接的，中途不是合法 JSON；保持原始字符串最保真，执行前再解析。这样也方便把原始参数展示给前端或写进日志。

**D4. max_tokens 为什么要丢弃工具调用？**

> 截断意味着参数可能不完整，执行一个半截参数的工具是危险的。所以整条响应里的工具调用全部丢弃，只保留已到达的文本；模型下一轮可以重新发起。

**D5. 流结束没有 finish_reason 怎么办？**

> 抛 `STREAM_TRUNCATED`。没有结束标记的流不能当成功，否则可能把截断的文本或参数当成完整结果。

**D6. 为什么不在 LLM 层重试？**

> 重试策略和业务有关：哪些错误可重试、退避多久、是否换模型，都不应该由底层库硬编码。库只抛稳定的 `LlmError(code)`，由 `agent/request-error` 监听器决定。

**D7. 怎么换成 Claude / OpenAI？**

> 实现同一个 `stream(options)` 协议，把提供方的流翻译成 `BlockStart/TextDelta/ToolCallDelta/Finish`，注册到 `LlmService` 即可。`agent/request` 还能按会话或策略改写 provider/model。当前只实现了 OpenAI 兼容协议。

### E. 工具与并发

**E1. 工具三段流水线各自能做什么？**

> pre 做准入，可以 allow 或 deny；execute 环绕真实执行，可以做计时、重试、替换；post 做结果采纳，可以改写内容或把成功推翻成 block 反馈。三段都是 waterfall，插件可以插任意一段。

**E2. deny 为什么单调？**

> 安全决策不能被下游翻回。上游返回 `PreToolDeny` 时不调 `next()`，整条链短路，后续监听器和默认放行都不会执行。测试里专门验证了「第一个 deny 胜出」。

**E3. 工具失败为什么不终止轮次？**

> 工具失败是模型可恢复的：把 `Error: ...` 作为工具结果回给模型，它通常能换个参数或换条路。终止轮次会让一次小失败毁掉整个对话。真正不可恢复的错误（流断开、请求失败）才走轮次错误。

**E4. 未知工具 / 非法 JSON 怎么处理？**

> 都转成错误结果，不抛异常。未知工具返回 `UNKNOWN_TOOL`，非法 JSON 返回 `INVALID_ARGS`。模型会看到错误文本并自行纠正。

**E5. 为什么要独占屏障？哪些工具能并行？**

> 写操作和未知工具不能并发，否则会有竞态或副作用顺序问题。只有连续一段显式 `is_concurrency_safe=True` 的工具才走并行池；遇到独占工具就断开批次，形成屏障。当前 3 个读工具安全，2 个写工具独占。

**E6. 并行结果怎么保证顺序？**

> 批次内用 `asyncio.gather`，返回顺序与输入顺序一致；然后提交点逐个按模型顺序 append `tool/result`。所以执行可以乱序，日志和模型看到的结果永远是模型调用顺序。

**E7. 一个并行工具抛异常会怎样？**

> 正常路径下 `run_tool_pipeline` 会把异常转成 `ToolRunFailure`，不会让 `gather` 失败。如果流水线本身有 bug 导致异常逃逸，`gather` 会向上抛，轮次进入 error 分支，取消合成会补齐未提交调用的结果。

**E8. 怎么新增一个工具？**

> 构造 `ToolDefinition(name, description, parameters, execute, is_concurrency_safe)`，交给 `ToolsPlugin`；或者写一个插件在 `apply` 里注册，注册返回的 disposer 自动进作用域。schema 只暴露白名单字段，execute 不会发给模型。

### F. 取消、错误、一致性

**F1. cancel 的实现？会杀死 agent 吗？**

> `cancel()` 取消 loop task，`_run()` 捕获 `CancelledError` 后做日志收口，然后继续 while 循环。所以只中止当前工作，loop 本身存活。默认清空 inbox，`keep_inbox=True` 可保留。

**F2. 取消时日志怎么保持自洽？**

> 两件事：已到达的文本前缀落一条 interrupted assistant 消息；所有未提交的 tool/call 补合成 tool/result。这样日志仍然可以完整投影，不会出现「有调用没结果」。

**F3. 为什么区分 outcome unknown 和 aborted before dispatch？**

> 语义不同：已经开工的调用可能已经产生了副作用，只是结果没来得及提交；未派发的调用一定没执行。模型和用户需要知道这两者的区别，前者不能盲目重试。

**F4. 轮次错误后 loop 还活着吗？**

> 活着。错误只终结该轮：记 `turn/end(status="error")` 和 `agent.last_error`，loop 继续服务后续 followup。这样一次模型故障不会让整个会话报废。

**F5. request-error 重试会不会无限循环？**

> 当前没有内置重试预算，理论上监听器可以一直返回 retry。这是有意简化：策略交给监听器。生产上我会加重试次数、退避、可重试错误码白名单。

**F6. 断线 / 重连会不会丢事件？**

> 不会。SSE 的 `since` 是排他游标，重连时带上已收到的最后 seq，后端从 seq+1 重放；前端还会按 seq 去重。唯一要注意的是 EventSource 原生重连会复用旧 URL，所以前端在 `onerror` 时主动 close 并重建 URL。

### G. SSE 与前端

**G1. 为什么用 SSE 不用 WebSocket？**

> 这里的通信是单向的：服务端推事件，客户端发消息走普通 POST。SSE 更简单、HTTP 友好、天然支持断线重连和 `Last-Event-ID`。代价是 EventSource 不能带自定义头，所以 token 走 query 兜底。

**G2. since 的语义？为什么排他？**

> `since=N` 表示「我已经收到第 N 条」，从 N+1 开始重放。这与 `Last-Event-ID` 的语义一致。mini-harness 的 seq 是 0 基，如果按包含式默认 0，会吞掉 seq 0；冒烟测试发现后统一成排他，默认 -1 从头重放。

**G3. EventSource 原生重连有什么坑？**

> 原生重连会复用第一次连接的 URL，里面的 `since` 是旧的，重连后可能重复收到大量事件。所以前端在 `onerror` 里主动 close，重建带最新 `lastSeq` 的 URL；再加指数退避和 seq 去重双保险。

**G4. 前端怎么去重和重放？**

> 维护 `lastSeq`，初始 -1；每个事件先比较 `lastEventId`，小于等于 `lastSeq` 直接忽略。重连时 URL 带 `since=lastSeq`，后端从下一条重放。切换会话时把 `lastSeq` 重置为 -1，因为新会话的 seq 从 0 重新计。

**G5. token 放 URL 安全问题？**

> 这是明确的取舍：浏览器 EventSource 不能设自定义头。当前是内网个人站，token 是登录态；更稳的做法是用 HttpOnly cookie，或者用 fetch + ReadableStream 自己实现 SSE，从而带上 header。公网部署前应该改。

**G6. 15 秒 ping 的作用？**

> 保活并尽早发现死连接。中间代理通常会断开长时间无数据的连接；定时发注释帧可以维持连接，也让客户端知道服务端还活着。

**G7. nginx / 代理要注意什么？**

> 必须对 `/api/agent/` 关闭 buffering，并设置 `X-Accel-Buffering: no`，否则事件会被代理缓存，前端看到的不是实时流。部署配置里已经处理了这一点。

**G8. 消息发送接口为什么立即返回？**

> agent loop 是常驻任务，HTTP 只负责往 inbox 投递 followup，不阻塞等待回答。回答和工具轨迹通过 SSE 跟读，`turn/end` 表示本轮结束。这样长回答不会卡住 HTTP 请求。

### H. 多用户与安全

**H1. 怎么保证工具以正确用户身份执行？**

> agent loop 是创建时 `create_task` 起的常驻任务，contextvar 随创建时刻快照进任务。所以 `AgentHost.create()` 在创建前显式 `set_current_user_id(user_id)`；工具执行时从 contextvar 取用户根，不会串到别的用户。

**H2. contextvar 为什么会进线程？**

> Python 3.11 的 `asyncio.to_thread` 会复制当前 context 到工作线程，所以用户身份会跟着进 `to_thread`。这样阻塞的文件 IO 不用改接口也能拿到正确身份。

**H3. 会话越权怎么防？**

> 所有端点都要求登录；`get_owned(agent_id, user_id)` 做归属校验；不存在或不是本人统一回 `BIZ_NOT_FOUND`，不泄露他人会话是否存在。SSE 开流前也会校验一次。

**H4. prompt injection 怎么防？**

> 当前是纵深防御的第一步：工具白名单、破坏性操作不开放、系统提示要求文件事实必须走工具。但这还不是完整方案。生产上要加工具级权限、人工审批、工具输出隔离、指令层级和输入清洗。我不会说现在已经解决了 prompt injection。

**H5. 为什么不做删除 / 移动 / 复制？**

> 权限模型里有 19 个 `FileOperatorType`，还没接进工具层。在这些能力没有按用户权限收口之前，给 agent 破坏性能力风险太高。所以只开放 3 个读工具和 2 个低风险写工具（新建文件夹、重命名）。

**H6. 多进程部署会怎样？**

> 当前会话在进程内存里，多 worker 下 SSE 可能落到另一个 worker，拿不到会话，表现是 40400。要水平扩展，需要把会话日志外置（Redis Streams / DB）、加按 agent 的路由或粘性会话，并用分布式锁保证同一 agent 只有一个 loop 在跑。

### I. 测试与质量

**I1. 50 个测试覆盖了什么？**

> events 10 个：waterfall 委托/短路/改写、serial 顺序、emit/drain、disposer、插件依赖与 LIFO；session 8 个：seq 单调、投影规则、空消息、interrupted、tool_call 归属；tools 15 个：白名单、三段流水线、deny 单调、异常转错误、未知工具、分片折叠；loop 17 个：端到端、工具往返、guard、重试、取消中流/中工具、keep_inbox、并行重叠、独占顺序、inbox 语义。

**I2. 没有真实 API 怎么测？**

> `MockProvider` 按脚本逐条吐出预设分片，确定性、无网络、无 key；耗尽抛 `SCRIPT_EXHAUSTED`。真实 provider 用 CLI 和后端冒烟手工验证。

**I3. run_async 为什么不用 pytest-asyncio？**

> 为了让运行时和测试都保持零第三方依赖。`tests/conftest.py` 里用一个 `run_async` 装饰器包 `asyncio.run`，足够覆盖现有测试。

**I4. 还缺哪些测试？**

> 真实 DeepSeek 的集成测试、前端浏览器端到端测试、长会话/压缩、多用户并发、性能与背压。当前单测主要覆盖机制和边界，不覆盖真实网络和 UI。

### J. 生产化与扩展

**J1. 怎么持久化 / resume？**

> 把 append-only 日志落到 JSONL 或 DB，启动时重放；工具调用和结果天然可恢复。还要处理版本迁移、崩溃修复、fork。dsh 有这些，mini 版有意砍掉。

**J2. 怎么支持多 agent / 子 agent？**

> AgentRegistry 已经是多 agent 的；缺的是作用域隔离、父子关系、结果回传和调度策略。可以在容器层加 scope 过滤，在 loop 层加 subagent 工具。

**J3. 怎么加人工审批？**

> 在 `tools/pre-execute` 挂一个插件：命中敏感工具时返回「待审批」决策，暂停该调用并向前端推审批请求；审批结果回来后再继续或 deny。日志里也要记录审批事件，保持可重放。

**J4. 怎么观测成本和延迟？**

> 当前没有 usage 计量。下一步在 provider 层解析 usage 块，落成事件；再加 turn/step/tool 的耗时指标、token 计数、错误码分布。事件日志本身就是很好的审计源。

**J5. 怎么限流 / 配额？**

> 三层：用户级并发/频率限制、会话级最大轮次和 token 预算、工具级调用预算。可以做成 `agent/pre-step` 和 `tools/pre-execute` 插件。

**J6. 怎么扩展到企业网盘 / S3？**

> 存储抽象层已经按接口拆好，工具只依赖 `registry` 和 `AbstractBaseFileService`。新增存储源实现后，工具层不需要改；真正要补的是各存储源的权限与路径语义一致性。

---

## 8. 压力题与「刁难」应对

### 8.1 「这不就是把 dsh 抄了一遍吗？」

> 架构是对照学的，我从不避讳。但落地上有三块是原项目没有的：Python async 事件分发、接入真实 DeepSeek 和 NAS 存储、以及取消/SSE/多用户身份这些工程边界。判断一个学习项目不能只看像不像，要看能不能讲清楚每个设计为什么存在、换掉会怎样、边界在哪。这些我都能落到代码和测试。

### 8.2 「50 个测试不算多，而且都是单元测试」

> 对，单测主要覆盖机制和边界，不覆盖真实网络和 UI。我的取舍是先把最容易错的逻辑用确定性测试锁住：取消合成、deny 单调、并行顺序、inbox 语义、投影规则。集成层用 CLI 和后端冒烟验证。生产上我会补真实 API 的集成测试和前端 E2E。

### 8.3 「没有持久化，重启就没了，这算完成吗？」

> 对这个阶段算完成，因为目标是先跑通机制和内网可用。会话内存态是明确写进 README 和接入层的边界，前端也处理了 40400 后自动新建会话。生产化路径很清楚：日志落 JSONL/DB，重放恢复，再做压缩和迁移。

### 8.4 「为什么不用官方 SDK？」

> 我想完全控制流式解析和错误码，直接用 httpx 打 OpenAI 兼容接口最直接。SDK 会隐藏分片和 finish_reason 的细节，而这些正是我想验证的。接入层用 SDK 也完全可以，只要翻译成同一个 `StreamChunk` 协议。

### 8.5 「多进程部署怎么办？」

> 当前不支持水平扩展，这是已知边界。要支持的话，会话日志必须外置，SSE 需要跨进程 pub/sub，同一 agent 的 loop 需要分布式锁或固定路由。单进程个人站阶段没必要提前上这些复杂度。

### 8.6 「token 放 URL 不怕泄露吗？」

> 怕，所以这是内网阶段的取舍。EventSource 不能带自定义头；更稳的方案是 HttpOnly cookie，或者 fetch + ReadableStream 自己实现 SSE。公网部署前会改掉。这个问题本身说明我在接入时意识到了约束，而不是无脑照搬。

### 8.7 「模型输出非法工具参数怎么办？」

> 参数预检会返回 `INVALID_ARGS`，不执行工具；模型看到 `Error: ...` 后通常能自行修正。流式参数在拼接完成前不解析，`max_tokens` 截断时整条工具调用丢弃。真正危险的是「参数合法但语义有害」，那要靠权限和审批，不是 JSON 校验。

### 8.8 「工具并行会不会有竞态？」

> 默认不会，因为默认独占，只有显式声明并发安全的连续读工具才并行。写工具、未知工具都是屏障。并行批次内用信号量限制并发数，结果按模型序提交。真正的风险是工具实现自己不是线程安全的，这由 `is_concurrency_safe` 的声明责任来保证。

### 8.9 「contextvar 在异步里不是不可靠吗？」

> contextvar 本身是可靠的；不可靠的是「在错误的时机 set」。这里的约束是：必须在创建 loop task 之前 set，因为 task 会快照当前 context。`AgentHost.create()` 把这一步收敛到一个点，并写了注释和测试。`to_thread` 也会复制 context，所以线程池里身份不丢。

### 8.10 「如果让你明天上线给 100 个用户用，你还缺什么？」

> 按优先级：会话持久化和多进程路由、限流与配额、工具审批和权限、可观测性（日志/指标/成本）、真实 API 的集成测试、前端 E2E、上下文压缩。当前版本适合内网小规模验证，不适合直接公网多租户。

### 8.11 「你这个项目最大的缺点是什么？」

> 功能边界窄：单 agent、单进程、内存态、没有压缩和审批。但这些是主动划的边界，不是没看到。真正的风险在于：如果需求快速膨胀，自研 harness 的维护成本会超过框架。所以我会在边界变化时重新评估，而不是为了「自研」而自研。

### 8.12 被问住时的通用话术

> 「这块我没有实测过，不想编。从设计上我的理解是……；如果要确认，我会用……验证。」
>
> 先澄清范围 → 讲已知的不变量 → 给出验证方案。面试官更在意你的推理方式，而不是你什么都知道。

---

## 9. 现场演示脚本

### 9.1 无网络、无 key 的安全演示

```bash
cd mini-harness

# 1) 两幕端到端演示：正常工具轮次 + guard 拦截
python3 examples/demo.py

# 2) 50 个确定性测试
python3 -m pytest tests/ -q
```

讲解点：
- 幕一：`tool/call → tool/result → assistant` 的事件序列。
- 幕二：guard 短路，模型只看到 `Error: ...`，轮次继续。
- 结尾：`derive_messages()` 打印的正是下一次请求的历史；卸载时 logging 插件的 LIFO 顺序。

### 9.2 有 key 时的 CLI 演示

```bash
cd DemoFile
source .venv/bin/activate
export DEEPSEEK_API_KEY=sk-...
python scripts/agent_console.py
```

可以输入：
- `列出所有存储源`
- `看看 /Bangumi 下有什么`
- `在 /Bangumi 下新建一个文件夹叫 测试`
- `:events` 重放完整事件序列

### 9.3 后端 / 前端演示

- 后端冒烟：登录 → 建会话 → 发消息 → 用 `curl -N` 看 SSE 帧 → 停止 → 断线重连。
- 前端：登录后文件页出现浮动按钮 → 打开抽屉 → 发消息 → 工具卡展开 → 停止 → 新对话。
- 演示前自己先走一遍浏览器验收（当前记录里浏览器点击验收还未完成），避免现场翻车。

### 9.4 演示失败时的兜底

- 没有网络/key：只跑 demo 和 pytest，讲事件序列。
- 模型不调工具：换更明确的提示词，或直接展示 `:events` 日志。
- SSE 被代理缓冲：本地直连后端，或确认 nginx buffering 已关。

---

## 10. 简历描述（可直接改写）

**版本一（一行）**

> 从零实现 1,766 行零依赖 Python Agent Harness（插件容器、三模式事件、仅追加日志、工具流水线、turn/step 状态机），并接入 NAS 全栈项目，实现 DeepSeek 流式对话与自然语言存储管理。

**版本二（三条）**

- 设计并实现插件式 agent loop：服务注入与 LIFO 生命周期、emit/waterfall/serial 三模式事件、仅追加会话日志与模型历史投影，核心零运行时依赖。
- 实现流式工具调用：LLM 分片按槽位折叠、工具 pre/execute/post 三段流水线、独占屏障与有界并行调度、取消时日志自洽合成。
- 完成全链路接入：DeepSeek provider、5 个存储工具、7 个 HTTP/SSE 端点、Vue 聊天抽屉；50 个确定性单测 0.05s 通过，DemoFile 78 个后端测试全过。

**版本三（STAR）**

> **背景**：个人 NAS 项目需要 agent 做存储管理，但现成框架隐藏了 loop 细节，线上问题难定位。
> **任务**：实现一个可测试、可扩展的最小 agent harness，并接入真实业务。
> **行动**：对照 dsh 架构实现 8 个核心模块；用仅追加日志保证可重放；用三模式事件做拦截扩展；用独占屏障 + 有界并行解决工具调度；用取消合成保证日志自洽；接入 DeepSeek、SSE、前端重连。
> **结果**：核心 1,766 行、零运行时依赖、50 个测试 0.05s；端到端支持查询目录、建文件夹、重命名；边界与下一步明确。

---

## 11. 反问面试官

按岗位方向选 2-3 个：

1. 团队现在的 agent 落地在哪些场景？最看重效果、成本还是延迟？
2. 这边更倾向自研 harness，还是基于 LangGraph / 内部框架做二次开发？
3. 线上 agent 的评测体系怎么做？有没有回归集和人工评估？
4. 工具权限和人工审批目前是怎么设计的？
5. 这个岗位前三个月最重要的目标是什么？
6. 后端和部署形态是什么？有没有多租户、多进程的约束？
7. 团队怎么看「自研基础设施」和「快速用框架」的取舍？

---

## 12. 红线：不要过度承诺

| 不要说 | 改成 |
|---|---|
| 「生产级 agent 框架」 | 「面向个人站/内网的最小实现，边界明确」 |
| 「支持任意模型」 | 「实现了 OpenAI 兼容协议，换其他提供方需要适配器」 |
| 「解决了 prompt injection」 | 「做了工具白名单和破坏性能力收口，完整防护还没做」 |
| 「高并发 / 分布式」 | 「单进程内存态，扩展路径已想清楚」 |
| 「零依赖」 | 「核心库零依赖，接入层用 FastAPI/httpx/SQLAlchemy」 |
| 「测试覆盖率很高」 | 「50 个测试覆盖核心机制和边界，未覆盖真实 API 与 UI」 |
| 「自研比 LangChain 好」 | 「在当前需求下更可控；需求变复杂会重新评估」 |
| 「完全复刻 dsh」 | 「对照 dsh 学习，按 Python 和业务做了裁剪与扩展」 |

---

## 13. 附录：代码地图（面试前对照）

| 主题 | 位置 |
|---|---|
| 容器 `provide` / 挂起插件激活 | `mini-harness/mini_harness/container.py:103` / `:214` |
| LIFO 卸载 | `mini-harness/mini_harness/container.py:141` |
| `emit` / `waterfall` / `serial` | `mini-harness/mini_harness/events.py:52` / `:83` / `:72` |
| 日志 `append` / `derive_messages` | `mini-harness/mini_harness/session.py:118` / `:131` |
| `BlockAssembler` 分片折叠 | `mini-harness/mini_harness/llm.py:75` |
| 工具三段流水线 | `mini-harness/mini_harness/tools.py:137` |
| `followup` / `cancel` | `mini-harness/mini_harness/agent.py:129` / `:146` |
| loop 主循环 / turn / step | `mini-harness/mini_harness/agent_loop.py:118` / `:139` / `:195` |
| 模型请求与重试 | `mini-harness/mini_harness/agent_loop.py:210` |
| 工具调度（屏障 + 并行） | `mini-harness/mini_harness/agent_loop.py:270` |
| 取消合成 | `mini-harness/mini_harness/agent_loop.py:348` |
| DeepSeek 流式解析 | `DemoFile/app/agent/provider.py:74` |
| 存储工具定义 | `DemoFile/app/agent/storage_tools.py:140` |
| `AgentHost` 建会话 / SSE | `DemoFile/app/agent/host.py:108` / `:148` |
| SSE 帧序列化 | `DemoFile/app/agent/serialize.py:62` |
| 路由与 SSE 端点 | `DemoFile/app/modules/agent/router.py:114` |
| 前端 EventSource 连接 | `MFN-vue/src/composables/agent/useAgentChat.js:245` |

---

## 14. 面试前 30 分钟速查

1. 过一遍第 0 节的 8 个数字。
2. 过一遍 1.2 的 30 秒稿和 1.3 的 2 分钟稿。
3. 在白纸上默画一次 turn/step 状态机和取消分支。
4. 挑 5 个最可能被问的：A1、B3、C1、F2、G2，口头答一遍。
5. 跑一次 `python3 examples/demo.py` 和 `pytest`，确认环境。
6. 提醒自己：主动说边界，比被问出来更加分。
