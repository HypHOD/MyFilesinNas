# MFN-vue 项目解析与面试准备

> 定位：`MFN-vue/` 是在 ZFile 4.5.0 前端（Vue 3 + Vite + Element Plus，MIT）基础上做二次开发的在线文件站前端。除了文件浏览 / 上传 / 预览 / 分享这些主体能力，还集成了 AutoBangumi 追番管理、公开只读看番页，以及基于 SSE 的 AI 文件助手。
>
> 这份文档的目标和 `mini-harness/INTERVIEW.md` 一样：**能讲清楚、能被追问、不吹牛**。所有数字与结论均基于当前仓库代码核实；无法证明的部分明确标注为“上游能力”或“未验证”。

---

## 0. 先记住这八个数字

1. **249 个源文件 / 23,763 行**：`src/` 下 107 个 `.vue`、68 个 `.ts`、74 个 `.js`；39 个页面、63 个组件。
2. **4 种上传策略**：`PROXY`（走后端 PUT）、`S3`（预签名直传）、`MICROSOFT`（OneDrive/SharePoint 100MB 分片）、`UPYUN`（签名表单）。
3. **7 类内置预览 + 2 个扩展入口**：内置 image/video/audio/text/pdf/office/three3d；扩展是 kkfileview 外部预览和图片画廊/文档模式；其余类型走下载兜底。
4. **3 个 axios 实例、3 套错误模型**：主站信封 `{code,msg,data}`、看番页字符串 code `'0'`、RSS 的 `msg_zh` + PATCH。
5. **4 个 Pinia store + 一组模块级单例 composable**：`global-config`、`storage-config`、`file-data`、`rss-program`；上传队列、选择器、分享态、Agent 流都是模块级单例。
6. **6 个 Agent REST 接口 + 1 条 SSE 事件流**：会话创建/查询/列表/发消息/中止/关闭 + `/events?since=N&token=...`。
7. **2 个后端**：主站 8080（DemoFile/FastAPI 系），RSS/AutoBangumi 7892（独立服务，经 `/rss-api` 代理）。
8. **一次生产构建 3,970 modules / 55.62s**（2026-10-19 实测，`pnpm build` 通过）：最大懒加载 chunk 是 PDF 预览 2.41MB、3D 789KB、视频 722KB；现代入口 714KB，legacy 入口 858KB + polyfills 162KB，构建器有 >500KB 警告。

补充一个诚实数字：**明确由我新增的 commit 约 1,100 行**（`b875b3b` Agent 接入 786 行 / 9 文件；`995583e` 公开看番页 329 行 / 6 文件），其余主体来自 ZFile 上游或此前整合的小项目。面试时按“二次开发 + 集成”认领，不按“从零写了 23k 行”讲。

---

## 1. 怎么讲这个项目

### 1.1 一句话版本

> 一个 Vue 3 + Vite 的在线文件站前端，支持多存储源、四种上传方式、多类在线预览、分享与目录权限，并集成 AutoBangumi 追番管理和基于 SSE 的 AI 文件助手。

### 1.2 30 秒版本

> 这个项目的主体是 ZFile 的前端，一个面向个人 NAS / 小团队的文件目录站：用户按存储源浏览文件，能上传、预览、生成直链、分享，管理员能配置存储源和权限。我在它上面做了三块扩展：第一，接入自研的 Agent 后端，用 SSE 做流式对话和工具调用展示；第二，做了一个完全游客视角的公开看番页，和登录态彻底隔离；第三，把 AutoBangumi 的 RSS 订阅、番剧管理、运行状态做成管理后台页面。前端技术栈是 Vue 3 + Vite + Pinia + Element Plus + Tailwind，构建和部署都走 Docker。

### 1.3 2 分钟版本

> 项目分三个入口。第一个是文件站：URL 直接表达状态，`/:storageKey/:fullpath` 决定当前存储源和目录，刷新、前进后退、分享链接都天然可用；文件列表、表格/卡片视图、右键菜单、快捷键、目录密码都围绕这条主链路。第二个是分享页：`/share/:shareKey`，支持密码和目录密码，文件下载链接由后端签发。第三个是公开看番页：`/bangumi`，不带任何登录凭证，只读访问后端给游客授权的 `/Bangumi` 白名单，视频播放器复用了文件站的 Artplayer 封装。
>
> 工程上比较有意思的是“多后端、多状态模型”的处理。主站请求走统一信封和全局拦截器，42000 跳登录、30000 确认、41000 展示字段错误；看番页单独建了一个 axios 实例，永不携带 token、永不跳登录；RSS 后端是 PATCH 语义、返回结构也不同，所以又单独一套实例和代理。状态上，跨页面共享的放 Pinia，生命周期比组件长的放模块级单例，比如上传队列、文件选择、Agent 的 SSE 连接，这样关掉抽屉、切换路由后流不会断。
>
> 我自己新增的部分主要是 Agent 前端和公开看番页。Agent 这边要解决 EventSource 不能带自定义头、浏览器原生重连会复用旧 `since`、断线后事件补发与去重、乐观 UI 与工具卡片合并这些细节。看番页这边重点是权限边界：游客 axios 不读 localStorage token，Header 不渲染存储源选择器，Agent 入口也隐藏，真正的授权仍由后端 guest 行决定。

### 1.4 5 分钟黑板版本（画图顺序）

1. 画浏览器里的 Vue SPA，标注三个入口：文件站、分享页、公开看番页。
2. 画分层：`pages → components → composables → api → http → 后端`，旁边挂 Pinia 和模块级单例。
3. 画三个后端：8080 主站、7892 RSS、对象存储（S3/OneDrive/又拍云）。说明哪些请求直传、哪些走后端。
4. 挑一条主线讲深：文件浏览（URL → loadFile → store → table/card）。
5. 再挑一条最能体现你工作的讲深：Agent SSE（EventSource → since/seq → 去重 → 工具卡片）。
6. 最后讲边界与反思：没有前端测试、typecheck 不可用、权限只做 UX、安全边界在后端。

### 1.5 和 mini-harness 一起讲（全栈故事）

如果面试官问“这个 AI 助手后端是什么”，可以顺势把两个项目串起来：

> 后端是我写的 mini-harness，一个零依赖的 Agent loop：插件容器、事件系统、append-only 会话日志、工具调度、取消合成，然后接了 DeepSeek 的流式 provider，用 SSE 把 `session/event` 实时推给前端。前端这条流要处理 `since` 排他重放、`seq` 去重、断线重连和工具调用卡片，正好和 mini-harness 的“模型可见即已记录”是同一套语义。这样讲能体现你不是只会画页面，而是能把前后端协议对齐。

---

## 2. 项目背景、定位与诚实边界

### 2.1 背景

- ZFile 的定位是“个人文件目录 / 公共文件库”，**不是多租户网盘**；一个管理员，多个存储源，访客可以按权限浏览。
- 前端是典型的 SPA：前台文件站 + 管理后台 + 安装页 + 登录页 + 分享页。
- 本项目在此之上补充了三条“个人需求驱动”的能力：
  1. 追番自动化：RSS 订阅 → 自动下载 → 重命名 → 本地媒体库；
  2. 公开看番：不登录也能看 `/Bangumi` 下的剧集；
  3. AI 文件助手：用自然语言查文件、问目录、做操作。

### 2.2 上游 vs 自研（面试必须说清楚）

| 模块 | 来源 | 证据 |
| --- | --- | --- |
| 文件站主体（浏览、上传、预览、分享、后台、设置） | ZFile 4.5.0 上游，本仓库二次开发 | `package.json` 名称 `zfile`、repo 指向 `zfile-dev/zfile-vue`、MIT |
| AutoBangumi RSS（4 个后台页 + API + store） | 随初始终合 commit `e40e1ae` 进入仓库，来自此前小项目 | `src/pages/admin/rss/*`、`src/api/rss/*`、`src/stores/rss-program.js` |
| 公开看番页 `/bangumi` | 自研，commit `995583e`（6 文件 / +329 行） | `src/pages/bangumi.vue`、`src/api/watch.js`、`src/http/watch.js` |
| AI 助手（抽屉 + SSE + 乐观 UI） | 自研，commit `b875b3b`（9 文件 / +786 行） | `src/components/agent/*`、`src/composables/agent/*`、`src/api/home/agent.js` |
| Docker / nginx 集成 | 自研，commit `4627307` | `docker-compose.yml`、`deploy/`、`vite.config.ts` 代理 |

**标准答法：**

> 主体不是我从零写的，这点我会明确说。我的工作是在一个成熟的开源前端上做集成和二次开发：理解它原有的路由、请求、权限和状态模型，然后把 Agent、公开看番、RSS 管理这些新能力接进去，同时保证原有文件站不回归。面试官如果问实现细节，我会聚焦自己写的那部分，以及我为了接入而必须吃透的原有机制。

### 2.3 用户与规模

- 目标场景是个人 NAS / 家庭内网 / 小团队文件库，不是高并发公网服务。
- 因此架构选择偏“简单、可部署、可维护”，而不是微前端、SSR、复杂缓存层。
- 如果被问“能支撑多少用户”，答：**没有做过压测，不能给数字**；前端是静态资源，瓶颈在后端和存储源，不在这一层。

---

## 3. 技术栈与架构

### 3.1 技术栈

| 层 | 选型 | 用途 |
| --- | --- | --- |
| 框架 | Vue 3.3（Composition API `<script setup>`） | 页面与组件 |
| 构建 | Vite 4.5 + pnpm 9.15.4，Node ≥ 18.16 | 开发、打包 |
| 状态 | Pinia 2.1 | 跨页面/跨组件共享状态 |
| 路由 | Vue Router 4.2 + `vite-plugin-pages` | 文件路由 + 手写兜底路由 |
| UI | Element Plus 2.9 + TailwindCSS 3.3 + Headless UI | 表格/弹窗 + 原子样式 + 无样式交互组件 |
| 图标 | `unplugin-icons` + `vite-plugin-svg-icons` + Heroicons | 文件类型图标、界面图标 |
| 请求 | axios 1.6 | 三套实例/拦截器 |
| 媒体 | Artplayer、hls.js、mpegts.js、aplayer、vue-pdf-embed、CodeMirror 6 | 预览能力 |
| 工具 | VueUse、dayjs、minimatch、path-browserify、file-saver、xlsx | 存储、时间、路径、下载、表格 |
| 质量 | ESLint、Prettier、TypeScript（渐进式） | 代码风格与类型 |

### 3.2 分层图

```
┌──────────────────────────────────────────────────────────────┐
│ 入口层  pages/ (39)                                          │
│   file.vue  share/[shareKey].vue  bangumi.vue  login.vue ... │
│   admin/**                                                   │
├──────────────────────────────────────────────────────────────┤
│ 布局层  layouts/                                             │
│   file.vue（前台）  admin.vue（后台）  default.vue  ...       │
├──────────────────────────────────────────────────────────────┤
│ 组件层  components/ (63)                                     │
│   layout/  file/view  file/preview  file/upload  share/ ...  │
├──────────────────────────────────────────────────────────────┤
│ 业务状态层  composables/                                     │
│   file/useFileData  useFileUpload  useFileOperator ...       │
│   agent/useAgentChat  share/useShareData  header/...         │
│   （其中很多是模块级单例）                                    │
├──────────────────────────────────────────────────────────────┤
│ 全局状态层  stores/ (Pinia, 4)                                │
│   global-config  storage-config  file-data  rss-program       │
├──────────────────────────────────────────────────────────────┤
│ API 层  api/home  api/admin  api/rss  api/tools  api/watch    │
├──────────────────────────────────────────────────────────────┤
│ HTTP 层  http/index.js + request.js（主站）                   │
│          http/watch.js（游客只读）  http/rss.js（PATCH）      │
└──────────────────────────────────────────────────────────────┘
         │                │                 │
     主站 8080        RSS 7892        对象存储直传
   （DemoFile）     （AutoBangumi）   （S3/OneDrive/又拍云）
```

### 3.3 目录速览

```
src/
├── api/            # 按后端分：home / admin / rss / tools / watch
├── assets/         # 图标、样式
├── components/     # 63 个组件：布局、文件视图、预览、上传、分享、Agent
├── composables/    # 业务逻辑；重点 file/、header/、share/、agent/
├── constant/       # 文件类型、响应码、存储商、时间单位
├── http/           # 主站拦截器、watch 实例、rss 实例
├── layouts/        # file / admin / default / notFound
├── modules/router  # 手写根路由与 catch-all
├── pages/          # 文件路由页面
├── stores/         # 4 个 Pinia store
├── styles/         # Tailwind 与全局样式
└── utils/          # 路径、文件、时间、二维码等纯函数
```

---

## 4. 启动链路与运行时配置

### 4.1 启动顺序

1. `index.html` 里先执行一段内联脚本：读 `vueuse-color-scheme` 或 `prefers-color-scheme`，在首屏绘制前给 `<html>` 加 `.dark`，避免暗色模式闪白。
2. `main.ts` 先创建 app，然后 `axios.get('/zfile.config.json')`；**无论成功失败都 `.finally()` 挂载**（`src/main.ts:16-20`）。
3. `App.vue` 用 `el-config-provider` 注入中文 locale；`router-view v-if="isRouterAlive"`，并通过 `provide('reload')` 暴露一个“卸载再挂载”的刷新方法（`src/App.vue:19-26`）。
4. 进入 `file` 布局后，`onBeforeMount` 拉 `/api/site/config/global`：未安装跳 `/install`，游客跳后端 `/guest`，否则把站点配置写进 `storage-config`，并把管理员配置的音视频/文本/Office 后缀合并进 `constant.fileTypeMap`（`src/layouts/file.vue:41-76`）。
5. 页面 `onBeforeMount` 再加载存储源列表和当前目录文件。

### 4.2 为什么用 `/zfile.config.json` 而不是环境变量

- 同一份 Docker 镜像要部署到不同环境，`baseUrl`、路由模式、骨架屏、画廊、后台表单密度都不同。
- 构建期环境变量会固化进 bundle，改一个地址就要重新构建；运行时 JSON 可以挂载覆盖。
- 代价：首屏多一次网络请求；如果配置文件 404，必须保证默认值可用。当前 store 有完整默认值，所以 `finally` 挂载是安全的。
- 追问“会不会白屏”：配置请求失败仍会挂载，展示默认配置；只有后端接口失败时，布局层会提示“无法连接服务端”。

### 4.3 `App.vue` 的 reload 技巧

- 切换站点设置、登录状态后，部分组件不会自动重新初始化。
- `reload()` 把 `isRouterAlive` 置 false，`nextTick` 再置 true，强制 `router-view` 卸载重建。
- 这是“暴力但可控”的做法；更优雅的是给页面提供明确的 `refresh()` 或把配置做成响应式依赖，但改造成本高。
- 面试可主动说：这是上游遗留方案，我知道它的代价（丢组件内部状态、重复请求）。

---

## 5. 路由与布局

### 5.1 文件路由

- `vite-plugin-pages` 扫描 `src/pages/**`，支持 `.vue/.md/.tsx`，自动生成 `~pages`。
- `vite-plugin-vue-meta-layouts` 读取每个页面底部的：

```yaml
<route lang="yaml">
meta:
  layout: file
  name: 看番
</route>
```

- `file.vue` 被 **显式排除**（`presets/tov.ts:47-55`），因为文件站需要 `/:storageKey/:fullpath(.*)*` 这样的 catch-all，文件路由生成不出来。
- 在 `src/modules/router.ts:6-19` 手动注册：

```ts
fileRoutes.push(
  { path: '/', meta: { layout: 'file' }, component: () => import('~/pages/file.vue') },
  { path: '/:storageKey/:fullpath(.*)*', meta: { layout: 'file' }, props: true,
    component: () => import('~/pages/file.vue') }
)
```

- 另加 `/login/:entry`（安全入口登录）与 `/admin → /admin/site-setting` 重定向（`router.ts:22-32`）。

### 5.2 布局

| 布局 | 用途 | 关键点 |
| --- | --- | --- |
| `file.vue` | 前台文件站、分享页、看番页、RSS 后台页 | Header/Footer、站点配置、`<AgentAssistant />` |
| `admin.vue` | 管理后台 | Headless UI 侧边栏（桌面固定 + 移动 Dialog）、导航分组、版本号、注销安全入口 |
| `default.vue` | 登录、安装、错误页 | 只渲染 `router-view` |
| `notFound.vue` | 404 | 同上 |

### 5.3 URL 即状态

- `storageKey` 与 `fullpath` 都来自路由参数，`useRouterData` 只做一层 computed 封装（`src/composables/useRouterData.js`）。
- 好处：刷新、前进后退、复制链接、分享都能复原现场；不需要把“当前目录”再存一份到 Pinia。
- 代价：路径要正确编码；代码用 `concatPathAndEncodeAll` 对每一段做 `encodeURIComponent`，保留 `/` 分隔符（`src/utils/models/path.ts:45-70`）。
- 注意：`useRouterData` 是模块级单例，router/route 只在 `App.vue` 初始化一次；在组件外使用也拿得到。

---

## 6. 请求层与错误模型

### 6.1 主站实例

`src/http/index.js`：

- `baseURL` 取 `globalConfigStore.zfileConfig.baseUrl`，`timeout: 0`（上传/下载可能很久）。
- 请求拦截器（`17-32`）：
  - token 优先 `localStorage['zfile-token']`，没有则从 cookie 读；
  - 只有“相对 URL”或显式 `containToken: true` 才带 `zfile-token`；
  - 带上 `axios-request: true` 与 `axios-from: serverAddress`，后端用它们区分前端请求和拼接回跳地址；
  - `console.time(url)` 记录耗时（调试遗留）。
- 响应拦截器（`44-65`）：
  - `responseIntercept === false` 直接返回原始 response；
  - `data.code !== 0` 时，除非 `showDefaultMsg === false`，否则 `ElMessage` 报错并 reject 整个 response；
  - 成功返回 `response.data`，业务层拿到的就是 `{code,msg,data}`。
- 错误分支（`66-148`）：
  - `41000`：格式化字段校验错误，拼 HTML 展示；
  - `42000`：未登录，整页跳 `/login?redirect=...`；
  - `30000`：无权限，确认后跳登录；
  - `2000*`：授权校验异常，提示去后台；
  - 403：展示响应体文本。

### 6.2 三个请求配置开关

| 开关 | 作用 | 例子 |
| --- | --- | --- |
| `showDefaultMsg: false` | 不弹全局错误，调用方自己处理 | 文件列表加载、Agent 会话 40400/50000 |
| `responseIntercept: false` | 不拆信封，返回原始 axios response | 文件单项信息 |
| `containToken: true` | 强制给外部 URL 带 token | 反代上传 PUT |

### 6.3 为什么有三个 axios 实例

1. **主站**：信封 + 全局跳转，适合登录态页面。
2. **`watchHttp`**（`src/http/watch.js`）：看番页必须“无论谁打开都是游客视角”。不能复用主站实例，因为主站拦截器会带 token、遇到 42000 会跳登录；这个实例不读凭证、只拼 `baseUrl + '/api'`，错误交给页面展示。
3. **`rssHttp`**（`src/http/rss.js`）：RSS 后端返回结构不同（`msg_zh`），且大量使用 `PATCH`，主站包装器不支持 PATCH；同时 RSS 后端没有 CORS 头，必须走 `/rss-api` 相对路径由 Vite/nginx 代理。

### 6.4 三套错误模型

| 后端 | 成功判定 | 错误消息 | 特殊处理 |
| --- | --- | --- | --- |
| 主站 | `data.code === 0`（数字） | `data.msg` | 41000/42000/30000/2000* |
| 看番 | `body.code === '0'`（**字符串**） | `body.msg` | 页面自己 set `error` |
| RSS | HTTP 2xx + 原样返回 | `msg_zh` 或 `detail.msg_zh` | `PATCH`、`/rss-api` 代理 |

> 这三套模型是历史集成结果，不是好设计。面试可主动说：如果重做，会定义统一的 API client + 错误码枚举，至少把“信封解析”抽成可配置的 response adapter。

---

## 7. 状态管理：Pinia + 模块级单例

### 7.1 四个 Pinia store

| store | 内容 | 特点 |
| --- | --- | --- |
| `global-config.ts` | `/zfile.config.json` 的运行时配置 | getter 提供 `serverAddress`、按 `isMobile` 切换后台表单/表格密度 |
| `storage-config.ts` | 站点配置、登录信息、当前目录配置、权限 | `permission` getter 组合 20 个权限位与当前选择状态 |
| `file-data.ts` | 文件列表源、加载数量、当前行、视图状态、音频列表 | `fileList` getter 负责切片、补图标、补 `fileType/preview` |
| `rss-program.js` | AutoBangumi 运行状态 | setup store，封装 start/stop/restart/refresh |

### 7.2 为什么还有一堆模块级单例

`useFileUpload`、`useFileSelect`、`useShareData`、`useAgentChat`、`useFileLink`、`useSetting`、`useFileLoading`、`useFilePwd` 都在模块顶层创建 `ref/reactive`，函数只返回同一份引用。

原因：

- **生命周期比组件长**：上传队列要在对话框关闭后继续跑；Agent 的 EventSource 要在抽屉关闭后保留/重连；文件选择要在表格、卡片、右键菜单之间共享。
- **跨组件通信**：`useFileSelect` 保存 `selectRows` 和表格实例方法，右键菜单、快捷键、批量操作都读它。
- **避免 props 层层传递**：文件页组件树很深（页面 → 视图 → 菜单 → 弹窗）。
- **不一定非 Pinia 不可**：这些状态没有 devtools 时间旅行、持久化、模块拆分需求，用普通 ref 更轻。

代价也很明确：

- 单例状态不会随路由自动重置，切存储源/目录时必须手动清理（例如 `loadFile` 成功后 `selectRows.value = []`）。
- 隐式依赖多，单元测试需要自己处理模块级状态。
- 与 Pinia 两套机制并存，新人需要知道“这个状态在哪”。

**如果重做：** 统一用 Pinia setup store，提供明确的 `reset()`；或者把“会话级单例”收敛到一个 `createSingleton()` 工厂并统一生命周期。

### 7.3 `storage-config` 的权限 getter

`src/stores/storage-config.ts:74-104` 把后端权限位与当前选择状态组合：

- 单选文件夹才允许“打开”；
- 单选文件才允许“预览”；
- 下载要求全部选中项都是文件；
- 直链/短链同时受站点开关与存储源权限约束；
- `uploadFolder = upload && newFolder`，避免没有建目录权限时还显示“上传文件夹”。

这只是 **按钮显隐和 UX**，真正的鉴权在后端；前端绕过也拿不到数据。

---

## 8. 文件浏览主链路

### 8.1 从 URL 到列表

```
URL /:storageKey/:fullpath
  → useRouterData 解析 storageKey / currentPath
  → Header 加载存储源列表；storageKey 不合法则跳第一个存储源
  → pages/file.vue onBeforeMount → useFileData.loadFile()
  → POST /api/storage/files { storageKey, path, password, orderBy, orderDirection }
  → file-data store.updateFileList(files)
  → 表格/卡片视图读 store.fileList
```

关键代码：`src/composables/file/useFileData.js:80-159`。

### 8.2 `loadFile` 做了哪些事

1. 没有 `storageKey` 直接返回。
2. 计算路径：显式传入优先，否则用当前路由。
3. 从密码缓存 `getPathPwd(loadPath)` 取目录密码。
4. 排序参数：用户选择优先，否则用站点默认 `defaultSortField/defaultSortOrder`。
5. 记录 `requestStorageId = storageKey.value`，请求返回后如果当前 storageKey 已经变了，**直接丢弃本次响应**（`96-106`）。这是处理“快速切换存储源导致旧请求后到”的竞态保护。
6. 成功：
   - 把 `passwordPattern` 写入密码缓存；
   - 非根目录时用 `path-browserify` 计算父目录，`unshift` 一条 `type: 'BACK'` 的返回行（`111-118`）；
   - `fileDataStore.updateFileList(fileList)`；
   - 清空选择、设置页面标题、加载当前目录配置（readme、权限、上传类型等）。
7. 失败：
   - `41021` 密码错误：警告 + 弹密码框；
   - `41020` 需要密码：直接弹密码框；
   - 取消时：根目录且 `rootShowStorage` 则回存储源列表，否则回上一级（`137-147`）。

### 8.3 为什么 `BACK` 行由前端造

- 后端返回的是“当前目录内容”，不含父级指针；前端用 `path.resolve(loadPath, '../')` 造一条返回行，表格/卡片就能统一处理。
- 好处：视图层不需要特判“如何返回”；坏处：`BACK` 不是真实文件，所有批量选择、删除、下载都要过滤它（`file-data.ts:46-49`、`CardFileView.vue` 的 `computedFileList`）。

### 8.4 `fileList` getter 做了什么

`src/stores/file-data.ts:44-68`：

- `loadFileSize === -1` 表示尚未加载，返回空数组；
- 如果第一行是 `BACK`，切片时要多取一条，保证“返回行 + N 个文件”；
- 遍历切片结果，补 `icon`，并根据后缀补 `fileType` 与 `preview` 布尔值；
- 这样模板里只需要 `item.icon`、`item.preview`，不用每个组件重复算。

### 8.5 加载更多

- 站点配置 `maxShowSize = 1000`、`loadMoreSize = 50`。
- `updateFileList` 把 `loadFileSize` 初始化为 `maxShowSize`；`LoadMoreFile` 组件每次增加 `loadMoreSize`。
- 这是**纯前端切片**：一次请求拿回整个目录，前端控制渲染数量。适合个人 NAS 的目录规模；如果目录有几万文件，应该改后端分页。

### 8.6 打开一行

`useFileData.js:182-231`：

- 右键菜单打开时，普通点击不触发打开；
- `FILE`：有 `preview` 权限则按 `fileType` 分发到视频/图片/文本/音频/Office/PDF/3D/kkfileview；没有预览权限或不支持的类型则直接下载；
- `ROOT`：跳到存储源根；
- `BACK` / `FOLDER`：`concatPathAndEncodeAll` 拼路由并 push；
- 进目录时清空 readme，避免上一目录的说明残留。

### 8.7 排序、搜索、快捷键

- 排序：`el-table` 的 `sort-change` → `sortChangeMethod` → 重新 `loadFile`，排序状态保存在模块级 `searchParam`。
- 搜索：站点配置 `searchEnable`；搜索请求走 `POST /api/storage/search`，结果同样写入 `file-data`。
- 快捷键（`useTableOperator.js:34-46`）：Esc 清空选择、Ctrl/Cmd+A 全选、Delete 批量删除、Backspace 返回上级。
- `allowShortcuts()` 会排除输入框、密码框、搜索框和弹窗，避免打字时误删。

---

## 9. 文件操作

`useFileOperator.js` 覆盖：

| 操作 | 关键点 |
| --- | --- |
| 批量下载 | 权限检查；可选二次确认（`enableNormalDownloadConfirm`）；`window.open(row.url)` |
| 新建文件夹 | 输入校验（禁止 `/`）；成功后重新加载 |
| 重命名 | 文件/文件夹两套接口；受存储源能力位限制 |
| 复制 / 移动 | `selectFolder` 选目标目录；源/目标密码都带上；部分失败弹详情 |
| 批量删除 | 确认框展示数量、非空文件夹警告；逐项带密码；部分失败弹详情 |

设计上：

- **每个操作都先做前端权限判断**，但后端仍会校验。
- **批量操作不是原子事务**：后端逐项执行，前端收集失败项，用 `BatchOperatorResult` 展示“哪些成功、哪些失败、原因是什么”。这比“整批回滚”更符合文件系统语义。
- **密码按路径传入**：`getPathPwd(path)` 命中 glob 缓存，避免用户每次操作都重新输入。

---

## 10. 上传：队列 + 四种策略

### 10.1 总体状态机

`useFileUpload.js` 是仓库里最大的文件（1,044 行），核心状态：

- `visible/uploadMode`
- `uploadingFileList` / `waitingFileList`
- `uploadingFileMap`（按 index 存进度、速度、状态）
- `cancelTokenSourceMap`（取消令牌）
- `maxFileUploads`（来自站点配置）

状态：`waiting → uploading → finished | error`，排序优先级 `error > uploading > waiting > finished`。

### 10.2 入队流程

1. 拖拽/选择/粘贴得到 `File` 列表。
2. 检查上传权限；读取 `webkitRelativePath` 或拖拽时的相对路径。
3. 文件夹拖拽：递归 `webkitGetAsEntry()`，展开目录和空目录；没有新建目录权限时会限制。
4. 超过 100 个文件弹确认。
5. 如果存储源要求 `needCreateFolderBeforeUpload`，先串行创建目录。
6. 每个文件生成 `uploadInfo` 和 cancel token，进入上传流程。

### 10.3 并发控制

`useFileUpload.js:494-500`：

- 当前 `totalUploading >= maxFileUploads` 时，把任务推进 `waitingFileList`；
- 每个上传结束（成功/失败/取消）都触发 watcher，从等待队列头部补位（`975-985`）；
- 并发数是纯前端限制，后端/对象存储仍可能承受更高并发。

### 10.4 四种上传策略

| 类型 | 协议 | 认证方式 | 分片/取消 | 代码 |
| --- | --- | --- | --- | --- |
| `PROXY` | 后端返回上传 URL，前端 `PUT multipart/form-data` | 主站 token（`containToken: true`） | cancelToken，整体上传 | `590-619` |
| `S3` | 后端给预签名 URL，前端直接 `PUT` 文件 | 签名在 URL 里，`withCredentials: false` | cancelToken；`Content-Type` 从 URL query 提取后删除 | `623-654` |
| `MICROSOFT` | OneDrive/SharePoint 分片上传 | 预签名 URL | 每片 100MB，`Content-Range`；202 继续，200/201 完成 | `657-727` |
| `UPYUN` | 又拍云签名表单 | `authorization` + `policy` | FormData POST，整体上传 | `730-749` |

几个容易追问的点：

- **S3 的 `Content-Type` 为什么藏在 URL 里？** 后端生成预签名时把必须匹配的 Content-Type 放进 query，前端要把它取出来放到请求头并从 URL 删除，否则签名校验失败。
- **OneDrive 的 202 语义**：202 表示“这一片收下了，继续下一片”；只有 200/201 才是整个文件完成。`start` 按 100MB 递增，进度用 `loaded + start` 计算真实字节数。
- **为什么所有直传都 `withCredentials: false`？** 避免把本站 cookie/token 发给第三方对象存储，减少凭证泄漏面；认证完全依赖预签名 URL。
- **UPYUN 为什么用 JSON 字符串传 uploadUrl？** 后端把 `{url, signature, policy}` 序列化后塞进 uploadUrl 字段，前端解析成 FormData。

### 10.5 取消、重试、进度

- 取消：`cancelTokenSourceMap.get(index).cancel()`；事件总线 `cancel-upload-${index}` 通知 UI。
- 重试：`retryUpload` 用 `silentMode=true` 重新走同一文件，不再新增一条列表记录。
- 进度：`onUploadProgress` 更新 `loaded/progress/speed`；速度用 `loaded / (now - startTime)`。
- 失败信息：`parseErrMessage` 区分 CORS、网络、HTTP 状态码和业务 code，尽量给出可操作提示。

### 10.6 局限（主动说，别等被问）

- 只有 OneDrive 做了**块级续传**；PROXY/S3/UPYUN 中断后只能整文件重传。
- 没有文件哈希去重、秒传、断点清单持久化。
- 并发是客户端限制，不能替代后端限流。
- 大文件依赖浏览器内存和网络稳定性；没有 Service Worker 后台续传。

---

## 11. 预览与播放

### 11.1 类型判断

- `constant.fileTypeMap` 定义 image/video/audio/text/executable/archive/pdf/office/three3d/document/kkfileview。
- `previewFileType` 是允许在线预览的子集。
- 管理员可以在站点设置里覆盖音频/图片/文本/视频/Office 后缀，布局层加载配置后会直接改 `constant.fileTypeMap`（全局可变配置，属于上游设计）。

### 11.2 视频播放器（`VideoPlayer.vue`）

- 基于 **Artplayer**，支持：
  - HLS：`Hls.isSupported()` 用 `hls.js/dist/hls.light.min`，否则用原生 `video.canPlayType('application/vnd.apple.mpegurl')`；
  - FLV：`mpegts.js`；
  - 弹幕：`artplayer-plugin-danmuku`，按文件名匹配弹幕文件；
  - 字幕：按文件名匹配同名字幕，多字幕可切换；
  - 上一集/下一集：从 `fileDataStore.fileListSource` 里找当前视频的索引；
  - 自动播放、自动连播、隐藏工具栏：`useStorage` 持久化到 localStorage；
  - 播放进度：`_h5_player_play_progress_` 存在 localStorage；
  - 外部播放器：IINA、VLC、PotPlayer、Motrix、nplayer、MX Player、迅雷协议等（`380-406`）。
- 移动端有独立的“上一集/下一集”工具栏。
- 看番页复用同一个播放器：把目录文件灌进 `fileDataStore.updateFileList`，字幕匹配和连播就能工作。

### 11.3 其他预览

| 类型 | 方案 | 注意点 |
| --- | --- | --- |
| 图片 | `v3-img-preview-enhance` 画廊 | 支持当前目录图片集合、索引、缩放 |
| PDF | `vue-pdf-embed` | 懒加载 chunk 2.41MB，是最大的预览包 |
| 文本/代码 | CodeMirror 6 | 纯前端只读渲染；文件内容仍需签名 URL |
| Office | OnlyOffice / 后端转换 | 配置来自 `zfile.config.json` 与站点设置 |
| kkfileview | 外部服务 iframe | URL 需要 base64 + 随机安全文件名，避免中文/特殊字符问题（`path.ts:72-107`） |
| 3D | Three.js 预览组件 | 懒加载 chunk 789KB |
| 音频 | aplayer | 支持播放列表 |

### 11.4 签名 URL 过期

- 文件 URL 是后端签发的短时效链接（看番页注释明确 30 分钟）。
- 播放长视频时，浏览器会持续发 Range 请求；如果 URL 过期，后续 seek 可能 403。
- 当前没有自动刷新签名逻辑，用户需要刷新目录。这是已知限制，面试可以主动提“更好的做法是播放器在 401/403 时重新请求文件 URL 并热替换”。

---

## 12. 分享

### 12.1 分享页流程（`pages/share/[shareKey].vue` + `useShareData`）

1. `initShare()` 拉分享信息；失败则 `shareInvalid = true`，展示“分享链接不可用”。
2. 需要密码且 URL 没有 `pwd` → 展示密码页；验证成功写 `shareVerified`。
3. 验证成功后把密码写入 URL query，确保后续下载始终带密码（`[shareKey].vue:150-153`）。
4. `loadShareFiles(path)`：
   - 请求分享文件列表；
   - `FILE` 项拼分享下载 URL；
   - 非根目录插入 `BACK`；
   - 用响应里的 `permission` 覆盖 `folderConfig`；
   - 区分分享密码与目录密码：目录密码只用 `popPassword({showRemember:false})`，不落缓存。
5. 排序、路径切换都走 `route.query.path`，并监听变化重新加载。
6. 取消目录密码时回退到“最后一次成功路径”，避免卡在错误目录。

### 12.2 分享创建与后台

- `CreateShareDialog`：选择文件/文件夹、过期时间、自定义分享 key（需权限）。
- 后台 `ShareListTable`：列表、复制链接、删除、清理过期分享。
- 分享下载 URL 由 `getShareFileDownloadUrlReq(shareKey, fullPath, password)` 生成，密码作为 query 参数。

### 12.3 分享密码放 URL 的权衡

- 好处：下载请求、刷新、复制链接都能继续工作，不需要额外会话。
- 坏处：密码进入浏览器历史、访问日志、Referer；如果分享页引用了第三方资源，可能泄漏。
- 当前是“分享密码”而非账号密码，风险可接受但不理想。
- 更好的方案：验证后用后端签发短期 share token，URL 只带 token；或者用 POST 换取 cookie。

---

## 13. 权限与目录密码

### 13.1 权限位

`storage-config.ts` 的 `permission` getter 组合了 20 个权限：open/preview/download/copyDownloadLink/rename/link/pathLink/shortLink/bothLink/copy/move/delete/upload/uploadFolder/search/newFolder/batchDownload/packageDownload/createShareLink/customShareKey。

- 后端在每个目录的配置里返回权限位；
- 前端结合“当前选中项类型/数量”计算按钮是否可用；
- **只做 UI 约束**，真正的越权请求由后端拒绝。

### 13.2 目录密码

`useFilePwd.js`：

- 两份缓存：
  - `zfile-pwd-cache` → localStorage，用户勾选“记住密码”时写入；
  - `zfile-pwd-full-cache` → sessionStorage，保存本次会话的所有密码（包括未勾选记住的）。
- key 是 `storageKey → glob pattern → password`；匹配用 `minimatch`。
- 路径会先拼上用户根目录 `user.rootPath` 再匹配；`**` 前没写 `/` 会自动修正。
- `popPassword` 同时支持 Promise 和旧式回调；密码框可配置是否显示“记住密码”。
- `clearPwdCache` 在用户主动清理时清空两份缓存。

### 13.3 安全反思

- 明文密码存在 Web Storage，XSS 可以直接读走；这是“便利性优先”的设计。
- sessionStorage 只限当前标签页，比 localStorage 稍好。
- 如果重做：不存明文，改存后端签发的短期目录 token；或者至少加密并设置更短的有效期。
- 面试时不要把它说成“安全设计”，要主动说是权衡。

---

## 14. AutoBangumi（RSS / 追番）

### 14.1 架构

- RSS 是**独立后端服务**（默认 7892），有自己的配置、数据库和下载器对接（qBittorrent）。
- 前端不直连，统一走 `/rss-api`：
  - 开发：Vite 代理 `/rss-api` → `http://127.0.0.1:7892`，并 rewrite 成 `/api`（`vite.config.ts:37-43`）；
  - 生产：nginx `location /rss-api/ { proxy_pass http://rss:7892/api/; }`。
- 这样浏览器看到的是同源相对路径，不触发 CORS；RSS 后端不需要加 CORS 头。

### 14.2 页面

| 页面 | 功能 |
| --- | --- |
| `/admin/rss` 追番总览 | 运行状态、版本、首次运行；启动/停止/重启；每 5 秒轮询状态（`admin/rss/index.vue:48-52`） |
| `/admin/rss/subscriptions` | RSS 列表、添加（名称/URL/聚合）、启用/禁用、删除 |
| `/admin/rss/bangumi` | 番剧列表、归档状态、删除 |
| `/admin/rss/setting` | 程序间隔、WebUI 端口、下载器类型/地址/账号/路径/SSL；保存后热重载 |

### 14.3 细节

- `rssHttp` 用 `PATCH` 做 enable/disable/updateConfig，主站包装器不支持 PATCH，所以必须独立实例（`http/rss.js:3-6`）。
- 错误消息优先取 `msg_zh` 或 `detail.msg_zh`（`http/rss.js:12-21`）。
- 设置页的密码是掩码 `********`，后端保存时还原；前端不接触明文。
- 状态轮询失败静默处理，后端没启动时页面仍可用。
- 订阅开关失败会回滚 `v-model` 的本地状态（`subscriptions.vue:110-120`），避免 UI 与后端不一致。

### 14.4 安全边界

- RSS API 本身没有鉴权（内网部署假设），所以**不能直接暴露公网**。
- 部署层应在 nginx 加 Basic Auth / IP allowlist，或只在内网访问。
- 面试时明确说：这是“网络边界即安全边界”的取舍，不是应用层鉴权。

---

## 15. 公开看番页 `/bangumi`

### 15.1 目标

- 不登录的访客可以浏览、播放 `/Bangumi` 白名单下的剧集。
- 不能因为本地有管理员 token 就变成管理员视角；也不能因为接口 42000 就跳登录。

### 15.2 隔离手段

1. **独立 axios** `watchHttp`（`src/http/watch.js`）：
   - 不读 localStorage/cookie；
   - 不挂主站拦截器；
   - 只拼 `baseUrl + '/api'`；
   - 错误不跳登录。
2. **公开 API 封装** `src/api/watch.js`：
   - `WATCH_STORAGE_KEY = 'local'`（当前硬编码，后续可改成取存储源列表第一项）；
   - `fetchWatchFiles(path)` → `POST /storage/files`；
   - `fetchWatchStorageConfig(path)` → `POST /site/config/storage`，用于拿游客权限位；
   - 自行解包字符串 `code === '0'`。
3. **后端 guest 授权行**：游客白名单根为 `/Bangumi`，权限（预览/下载）由后端决定，前端只展示。
4. **布局隔离**：
   - Header 在看番页隐藏存储源选择器（`Header.vue:121`）；
   - `useHeaderStorageList.rootPathAction` 直接跳过 `/share` 和 `/bangumi`，避免把看番列表覆盖成存储源列表（`useHeaderStorageList.js:59-67`）；
   - `AgentAssistant` 只在登录且非分享/看番页显示（`AgentAssistant.vue:197-203`）。
5. **播放器复用**：把当前目录文件写进 `fileDataStore.updateFileList`，播放器的上一集/下一集、字幕匹配都从 `fileListSource` 找。

### 15.3 页面结构

- 面包屑：`番剧库 / 剧集目录 / …`，用 `pathStack` 维护；
- 目录卡片网格（FOLDER）+ 剧集列表（FILE 且后缀属于 video）；
- 点击剧集：`updateCurrentClickRow(row)` → `openDialogWithData(row.name)`；
- 加载/错误/空态三套 UI；
- 每次进目录或刷新都重新拉取，因为签名 URL 有有效期。

### 15.4 已知限制

- `WATCH_STORAGE_KEY = 'local'` 是硬编码，多存储源场景需要改。
- 没有分页/搜索，目录大时依赖后端返回量。
- 签名 URL 30 分钟，长视频 seek 可能过期（见 11.4）。
- 游客权限完全依赖后端 guest 行配置；前端隐藏按钮不等于阻止请求。

---

## 16. AI 助手：SSE + 乐观 UI

### 16.1 组成

- `src/components/agent/AgentAssistant.vue`（318 行）：悬浮按钮 + 非模态右侧抽屉（桌面 420px，移动 100%），消息气泡、工具卡片、输入框、停止/新会话。
- `src/composables/agent/useAgentChat.js`（385 行）：模块级单例状态与 SSE 生命周期。
- `src/api/home/agent.js`（53 行）：6 个 REST 接口 + 1 条 SSE：
  - `POST /api/agent/session`
  - `GET /api/agent/:id`
  - `GET /api/agent/sessions`
  - `POST /api/agent/:id/message`
  - `POST /api/agent/:id/cancel`
  - `DELETE /api/agent/:id`
  - SSE：`GET /api/agent/:id/events?since=N&token=...`
- 挂载在 `layouts/file.vue:16`，只在文件站布局出现。

### 16.2 会话生命周期

1. 打开抽屉：
   - 内存有 `sessionId` → 直接连接；
   - 否则读 localStorage `zfile-agent-session-id` → `GET /api/agent/:id` 校验；
   - 40400（后端重启/会话被删）→ 新建会话；
   - 50000（未配置模型 key）→ `enabled = false`，UI 进入空态，不发请求。
2. 新会话：
   - 清空消息、`lastSeq = -1`、断开旧流；
   - 创建成功后连接；
   - 旧会话再异步 DELETE，失败不影响新会话。
3. 关闭抽屉：断开 EventSource，但状态保留；下次打开从 `lastSeq` 继续。
4. 卸载：`dispose()` 关闭流、关闭抽屉。

### 16.3 为什么用 EventSource

- 服务端只是单向推送事件，不需要客户端在同一连接上发消息；SSE 比 WebSocket 简单，天然适合 HTTP/nginx 基础设施。
- 限制：EventSource **不能设置自定义请求头**，所以 token 只能放 query：`?token=...`（`useAgentChat.js:253-255`）。
- 代价：token 可能进入访问日志/历史；缓解方式是使用短期 token 或改用 cookie 鉴权。

### 16.4 断线重连（重点）

原生 EventSource 会自动重连，但会复用**创建时的 URL**，也就是旧的 `since`；后端会重复推已经收到的事件，甚至漏掉新事件。因此：

1. `onerror` 里先 `source.close()`，置空；
2. 用当前 `lastSeq` 重建 URL；
3. 指数退避 `1s / 2s / 4s`，最多 3 次；
4. 超过 3 次进入 `diagnose()`：先查会话状态，40400 则新建会话并提示“会话已失效”，其他错误进入 failed；
5. `if (es !== source) return` 忽略已被替换的旧连接回调，避免旧连接把新连接关掉（`useAgentChat.js:263-277`）。

### 16.5 事件处理与去重

- 每个 SSE 事件都带 `lastEventId`，后端从 0 开始单调递增。
- 前端 `lastSeq` 初始 -1；收到事件时 `seq <= lastSeq` 直接丢弃（`143-146`）。
- `since` 是**排他**语义：只补 `seq > since` 的事件，所以断线重连不会重复渲染最后一条。
- 事件类型：
  - `user/message`：如果存在 pending 的同文本乐观气泡，就标记完成，否则新增；
  - `assistant/message`：遍历 content，text 推消息，tool_call 走 `upsertToolCall`；
  - `tool/call`：按 `callId` upsert 工具卡片；
  - `tool/result`：按 `callId` 填结果、错误标记、状态 done；
  - `turn/start`：running = true；
  - `turn/end`：running = false，error/canceled 推系统提示；
  - `system/message` 是系统提示词，不渲染；`step/*` 不在 UI 粒度内。

### 16.6 乐观 UI 的细节

- 发送时先 push 一条 `pending: true` 的用户气泡；
- 后端回显 `user/message` 时按“role=user + pending + 文本相同”匹配，把 pending 置 false；
- 发送请求失败：把最后一条匹配的 pending 气泡标 `failed = true`；
- 这个匹配是文本级，重复发同一句话可能匹配错；更稳的是客户端生成 `clientMessageId` 并在协议里回传。

### 16.7 工具卡片

- 模型的 `assistant/message` 里可能已经带 `tool_call` 块，随后又会收到 `tool/call` 事件；`upsertToolCall` 用 `callId` 去重。
- `tool/result` 到达后填 `result/isError/status`，UI 用不同图标表示运行中/成功/失败。
- 工具卡片可折叠，适合展示文件查询、目录遍历等大段结果。

### 16.8 安全与部署

- 只渲染纯文本（没有 `v-html`），避免模型输出直接变成 HTML。
- token 在 query，nginx 访问日志要脱敏；生产建议改短期 token。
- 部署时 nginx 必须对 `/api/agent/` 关闭 buffering（`proxy_buffering off`），并放宽 `proxy_read_timeout`，否则 SSE 会被缓冲成“一次性返回”或提前断开。
- 后端侧还要处理跨 worker 的 session 亲和/共享日志；这是 mini-harness 与部署层共同的问题。

---

## 17. 构建与工程化

### 17.1 Vite 插件栈（`presets/tov.ts`）

| 插件 | 作用 | 代价/注意 |
| --- | --- | --- |
| `@vitejs/plugin-vue` | SFC | — |
| `vite-plugin-pages` | 文件路由 | 魔法；`file.vue` 需手动排除 |
| `vite-plugin-vue-meta-layouts` | 按 `route.meta.layout` 套布局 | 需要在 SFC 写 YAML 块 |
| `unplugin-auto-import` | 自动导入 Vue/Pinia/Router/VueUse + stores/composables/constant/components | 隐式依赖；生成 `auto-imports.d.ts` 与 ESLint globals |
| `unplugin-vue-components` | 自动注册 Element Plus/Headless UI/VueUse 组件与图标 | 组件来源不直观 |
| `unplugin-icons` | Iconify + 自定义 SVG 集合 | 自动安装图标包 |
| `vite-plugin-svg-icons` | `src/assets/icons` 生成 symbol sprite | 文件类型图标 |
| `@vitejs/plugin-legacy` | 兼容 chrome49/firefox51/edge1，注入 polyfill | 产物变大、构建变慢 |
| `vite-plugin-use-modules` | 自动加载 `src/modules` | 路由模块自动注册 |
| `vite-plugin-compression` | gzip/brotli | 当前 `disable: true`，压缩交给 nginx |
| `rollup-plugin-visualizer` | 体积分析，`pnpm vis` | 开发依赖 |
| `vite-plugin-vue-devtools` | 开发期调试 | 仅 dev |

### 17.2 自动导入的边界

- 自动导入目录包含 `src/stores/**`、`src/composables/**`、`src/constant/**`、`src/components/**`，所以代码里经常直接出现 `useFileData()`、`constant`、`ElMessage`，看不到 import。
- 好处：模板短、重构移动文件时少改 import。
- 坏处：新人难追踪来源；IDE 依赖生成的 `.d.ts`；同名符号可能冲突。
- 面试观点：DX 优先的取舍，团队大/多人协作时应该加 lint 规则或收敛目录。

### 17.3 构建与质量现状

- `pnpm build`：2026-10-19 实测通过，3,970 modules，55.62s。
- 构建产物按路由/预览组件懒加载，但仍有 >500KB chunk：
  - `PdfViewer` 2.41MB、`Three3dPreview` 789KB、`VideoPlayer` 722KB、`TextViewer` 613KB；现代入口 714KB，legacy 入口 858KB（另有 162KB polyfills）。
- `pnpm typecheck` 当前不可用：`vue-tsc 1.6.5` 与 TypeScript 5.7 组合会报 “Search string not found”；因此实际用 `pnpm build` 做编译门禁。
- 没有前端测试框架（无 vitest/jest/cypress/playwright），没有 CI 配置。
- 代码风格：Prettier 制表符、无分号；`.js` 与 `.ts` 混用，类型覆盖不完整。

### 17.4 如果补质量

优先级建议：

1. 修 typecheck（升级 vue-tsc 或锁 TS 版本），先让 CI 能跑；
2. 给纯函数（path/time/file/上传错误解析）补 Vitest；
3. 给 `useAgentChat` 的 `handleEvent` 做事件序列单测（纯函数化后很容易）；
4. Playwright 覆盖三条黄金路径：登录 → 浏览 → 预览；上传；分享密码访问；
5. 把 `pnpm build` 放进 CI，防止 chunk/路由回归。

---

## 18. 设计决策与权衡表

| # | 决策 | 选择 | 理由 | 代价 |
| --- | --- | --- | --- | --- |
| 1 | 是否重写 | 基于 ZFile 二次开发 | 文件站能力成熟，重写成本高 | 继承上游结构和技术债 |
| 2 | 运行时配置 | `/zfile.config.json` | 一镜像多环境 | 首屏多一次请求 |
| 3 | 路由 | 文件路由 + 手写 catch-all | 减少样板，文件站需要动态路径 | 例外规则不直观 |
| 4 | 请求封装 | 全局信封拦截器 | 业务层代码短 | 与后端强耦合，三套模型并存 |
| 5 | 看番隔离 | 独立 axios | 游客视角、永不跳登录 | 代码重复、错误处理分裂 |
| 6 | RSS 隔离 | 独立 axios + 代理 | PATCH/错误结构不同、无 CORS | 多一层代理配置 |
| 7 | 状态 | Pinia + 模块单例 | 长生命周期状态简单直接 | 两套机制、重置困难 |
| 8 | URL 状态 | storageKey/fullpath 进路由 | 可刷新、可分享、可后退 | 编码复杂、catch-all 路由 |
| 9 | 文件列表 | 一次拉全量 + 前端切片 | 个人 NAS 目录不大 | 大目录不适用 |
| 10 | 权限 | 前端镜像 + 后端兜底 | 按钮即时反馈 | 前端权限不是安全边界 |
| 11 | 上传 | 四策略按存储源分发 | 兼容代理/S3/OneDrive/又拍云 | 分支多、测试面大 |
| 12 | 预览 | 外部服务/播放器复用 | 快速覆盖多格式 | 包体积、签名过期、CORS |
| 13 | 分享密码 | URL query 携带 | 下载/刷新不断链 | 历史/日志/Referer 泄漏 |
| 14 | 目录密码 | Web Storage 明文缓存 | 体验好、实现简单 | XSS 可读、安全弱 |
| 15 | Agent 传输 | SSE + since 重放 | 单向流、基础设施简单 | 不能带 header、需手动重连 |
| 16 | Agent UI | 乐观气泡 + 事件日志为准 | 输入即时反馈 | 文本匹配有歧义 |
| 17 | 自动导入 | 目录级 auto-import | 模板简洁 | 隐式依赖、IDE 依赖 d.ts |
| 18 | 兼容性 | legacy 构建 | 覆盖老浏览器 | 产物大、构建慢 |
| 19 | 测试 | 无 | 时间/范围限制 | 回归靠手工，不能吹 |

---

## 19. 高频 Q&A

### A. 项目与选型

**A1. 一句话介绍你的项目。**  
见 1.1。注意先说“二次开发”，再说扩展。

**A2. 为什么选 Vue 3 而不是 React？**  
主体是上游选型；Vue 3 的 Composition API 适合把“文件列表/上传队列/SSE”这类逻辑抽成 composable，Element Plus 在后台表格场景成熟，团队上手成本低。不是技术优劣判断，是生态与维护成本。

**A3. 为什么同时用 Element Plus 和 Tailwind？**  
Element Plus 负责表格、弹窗、表单等复杂交互；Tailwind 负责布局、间距、响应式和小组件样式。两者职责不同。代价是样式来源两套，需要约定哪层用哪套。

**A4. 为什么不用 Nuxt/SSR？**  
这是登录后/内网型 SPA，SEO 需求低；SSR 会引入服务端运行环境和鉴权转发复杂度，收益不明显。看番页如果要做公网 SEO，可以单独考虑 SSR/预渲染。

**A5. 为什么基于 ZFile 而不是重写？**  
文件浏览、上传、对象存储适配、分享、后台配置都是成熟能力；重写会把时间花在重复造轮子上。我的目标是验证“能否在成熟前端上安全地接入新后端能力”，这更接近真实工作。

**A6. 这个项目最难的点是什么？**  
不是页面，是**边界**：三种后端、三套错误模型、游客/登录两套身份、SSE 重连与去重。把这些边界理清，代码才不会互相污染。

**A7. 你具体负责什么？**  
Agent 前端、公开看番页、RSS 后台集成、Docker/代理配置；以及为接入而吃透的文件浏览/请求/权限主链路。主体文件站来自上游。

**A8. 项目有多少用户？**  
个人/家庭内网场景，没有公网压测数据。不给虚构数字。

### B. 架构与工程化

**B1. 描述一下整体架构。**  
见 3.2。按“页面 → 布局 → 组件 → composable → API → HTTP → 后端”讲，旁边补 Pinia 和单例。

**B2. 运行时配置怎么做的？**  
`main.ts` 先拉 `/zfile.config.json`，写入 `global-config`，`.finally()` 挂载。好处是一镜像多环境；代价是首屏多一次请求。

**B3. 为什么 `file.vue` 要手动注册路由？**  
因为需要 `/:storageKey/:fullpath(.*)*` catch-all，文件路由插件无法从文件名推导。其余页面仍走文件路由。

**B4. 自动导入的原理和风险？**  
`unplugin-auto-import` 在编译期分析模板/脚本中的标识符，自动插入 import；`unplugin-vue-components` 自动注册组件。风险是隐式依赖、同名冲突、IDE 依赖生成的 `.d.ts`。

**B5. 为什么 Pinia 和模块级单例混用？**  
Pinia 适合跨页面、需要 devtools/持久化的状态；模块级单例适合“必须活过组件卸载”的运行时状态（上传、SSE、选择）。混用是历史与务实的结果，不是理想架构。

**B6. 怎么管理多个后端？**  
按后端分实例：主站、watch、rss；API 层按目录分 `home/admin/rss/tools/watch`；代理层在 Vite 和 nginx 各配一份，保持开发/生产一致。

**B7. 构建产物怎么优化？**  
路由和重预览组件已经懒加载；Element Plus 按需引入；压缩交给 nginx（Vite compression 关闭）。还能做的是 manualChunks 拆 PDF/3D/视频、移除 legacy 或按浏览器分发、分析 `stats.html`。

**B8. 为什么 typecheck 坏了不修？**  
这是已知技术债：`vue-tsc 1.6.5` 与 TS 5.7 不兼容。当前用 `pnpm build` 做编译门禁；正确做法是升级 vue-tsc 或锁 TS 版本，并把 typecheck 放进 CI。面试时不要掩饰。

**B9. 为什么大量 `.js`？**  
历史代码以 JS 为主，TS 是渐进引入；类型收益在纯函数和 store 上更明显，业务组件改造成本高。代价是类型覆盖不完整。

**B10. 没有测试，你怎么保证质量？**  
诚实说：目前靠 `pnpm build` + 手工回归，覆盖文件浏览、上传、预览、分享、看番、Agent。然后给出补测试的优先级（见 17.4），不要声称“有测试”。

### C. 文件浏览

**C1. 从 URL 到列表的完整链路？**  
见 8.1。面试时按“路由 → storageKey → loadFile → store → 视图”五步讲。

**C2. 为什么把路径放在 URL？**  
可刷新、可分享、可后退；URL 是唯一状态源，store 只做投影。

**C3. 快速切换存储源时旧请求后到怎么办？**  
`requestStorageId` 快照；响应回来时和当前 `storageKey` 比较，不一致直接丢弃（`useFileData.js:96-106`）。

**C4. `BACK` 行怎么来的？为什么前端造？**  
后端只返回当前目录内容；前端用 `path.resolve(loadPath, '../')` 造返回行，视图层统一处理。所有批量操作要过滤 `BACK`。

**C5. 图标和预览标志在哪算？**  
`file-data.ts` 的 `fileList` getter 里补 `icon/fileType/preview`，模板只读结果，避免重复计算。

**C6. 分页怎么做的？是后端分页吗？**  
不是，一次拉全量，前端按 `loadFileSize` 切片，默认最多 1000，加载更多每次 +50。个人 NAS 够用；大目录应改后端分页。

**C7. 表格和卡片视图怎么共享状态？**  
都读 `fileDataStore.fileList`；选择状态在 `useFileSelect` 单例；切换视图不重新请求。

**C8. 快捷键怎么避免误触？**  
`allowShortcuts()` 排除输入框、搜索框、密码框、弹窗；Esc 清选择、Delete 批删、Backspace 返回。

**C9. 目录密码流程？**  
`getPathPwd` 从缓存按 glob 匹配；41020/41021 弹框；确认后带密码重载并写缓存；取消则回上级或存储源列表。

**C10. 刷新后视图模式还在吗？**  
在，`useSetting` 用 `useStorage('zfile-setting-cache')` 持久化表格/卡片、画廊参数。

### D. 上传

**D1. 上传完整链路？**  
选择/拖拽 → 权限与数量检查 → 预建目录 → 入队 → 并发闸门 → 请求上传地址 → 按 `uploadType` 分发 → 进度/取消/重试 → 完成后刷新列表。

**D2. 为什么需要四种策略？**  
不同存储源的上传协议不同：代理上传适合小文件/统一鉴权；S3 预签名适合直传；OneDrive 必须分片；又拍云要签名表单。抽象点就在 `metadata.uploadType`。

**D3. 并发怎么控制？**  
`maxFileUploads` 闸门；超出进 `waitingFileList`；每个任务结束从队头补位。只在前端限流。

**D4. 文件夹拖拽怎么实现？**  
`DataTransferItem.webkitGetAsEntry()` 递归读取目录；`webkitRelativePath` 保留相对路径；空目录单独处理；没有新建目录权限时限制。

**D5. 为什么上传前要建目录？**  
部分存储源不会自动创建父目录；`needCreateFolderBeforeUpload` 为 true 时先串行 mkdir，再上传文件。

**D6. S3 直传注意什么？**  
预签名 URL、`withCredentials: false`、`Content-Type` 必须与签名一致（从 URL query 提取）、CORS 要允许 PUT、URL 有有效期。

**D7. OneDrive 分片细节？**  
100MB 一片，`Content-Range: bytes start-end-1/total`；202 继续，200/201 完成；进度加 `start` 偏移；每片重建 cancel token。

**D8. 取消/重试怎么做？**  
`cancelTokenSourceMap` 按文件 index 存 token；取消调用 `cancel()`；重试用 `silentMode` 避免重复列表项。

**D9. 支持断点续传吗？**  
只有 OneDrive 是块级续传；其他策略中断后整文件重传。没有哈希秒传/持久化断点清单。

**D10. 上传安全边界？**  
直传不携带本站凭证，依赖预签名 URL；URL 泄漏风险由后端有效期和权限控制；前端不能替代服务端校验。

### E. 预览与播放

**E1. 支持哪些预览？**  
图片、视频、音频、文本、PDF、Office、kkfileview、3D、Markdown/代码；其余下载兜底。

**E2. 视频怎么支持 HLS/FLV？**  
HLS：`Hls.isSupported()` 用 hls.js，否则原生 HLS；FLV：mpegts.js；Artplayer 统一 UI。

**E3. 弹幕/字幕/连播怎么匹配？**  
按文件名去扩展名匹配同名字幕/弹幕；连播从 `fileListSource` 找当前索引的下一项；开关状态用 `useStorage` 持久化。

**E4. kkfileview URL 为什么 base64？**  
把目标文件 URL + 安全文件名编码后作为 `url` 参数，避免中文/特殊字符和编码歧义；随机文件名避免冲突。

**E5. 预览 URL 过期怎么办？**  
当前需要刷新目录重新拿签名 URL；没有自动续签。长视频 seek 可能 403，这是已知限制。

### F. 分享、权限与安全

**F1. 分享页完整流程？**  
见 12.1：分享信息 → 密码验证 → 文件列表 → 目录密码 → 下载 URL → 排序/路径。

**F2. 分享密码放 URL 有什么问题？**  
历史、日志、Referer 泄漏；便利性换来的。更好是短期 share token 或 POST 换 cookie。

**F3. 目录密码缓存怎么设计？**  
localStorage 存“记住”的，sessionStorage 存本次会话全部；key 是 storageKey + glob；minimatch 匹配；清空有入口。

**F4. 前端权限判断有意义吗？**  
有 UX 意义，没有安全意义。真正鉴权在后端；前端隐藏按钮只是减少误操作。

**F5. 41000/42000/30000/41020/41021 分别是什么？**  
41000 参数错误；42000 未登录；30000 无权限；41020 需要目录密码；41021 密码错误。分别对应字段提示、跳登录、确认跳登录、弹密码框、警告 + 弹框。

**F6. 记住密码明文存 localStorage 安全吗？**  
不安全，XSS 可读。属于体验优先的权衡；重做会改短期 token 或加密 + 更短有效期。

**F7. 自定义 JS/CSS 注入的风险？**  
管理员可在站点设置里注入脚本，等于把后台配置变成 XSS 入口；只应信任管理员，公网部署要限制后台权限。这是上游能力，不是我的设计。

**F8. 项目里有哪些 XSS 面？**  
`dangerouslyUseHTMLString` 展示后端消息/文件名、Markdown 公告、自定义 JS、kkfileview iframe。Agent 消息是纯文本渲染，没有 `v-html`。

**F9. token 为什么同时支持 localStorage 和 cookie？**  
兼容不同登录/反代形态；优先 localStorage，没有则读 cookie。代价是两处都可能被 XSS 读取。

### G. RSS 与看番

**G1. RSS 为什么独立后端？**  
AutoBangumi 是独立 Python 服务，有自己的配置、数据库和下载器；把它塞进主后端会耦合升级和故障域。前端用代理保持同源。

**G2. 为什么单独 axios 和 `/rss-api`？**  
PATCH 主站包装器不支持；错误结构不同；后端无 CORS，必须相对路径代理。

**G3. 状态为什么轮询？**  
运行状态是低频变化的小数据，5 秒轮询实现简单、无需长连接；SSE 留给 Agent 这种高频事件流。

**G4. 公开看番页怎么保证游客视角？**  
独立 axios 不读 token、不跳登录；后端 guest 行决定权限；Header 隐藏存储源选择；Agent 隐藏。

**G5. 为什么硬编码 `storageKey = 'local'`？**  
当前部署只有一个 local 存储源，先固定；多存储源时应从 `/storage/list` 取或由配置决定。

**G6. 看番页怎么拿到文件 URL？**  
`POST /storage/files` 返回带签名的短时效 URL；没有直链拼接。

**G7. 长视频签名过期怎么办？**  
当前刷新目录；更好的方案是播放器 403 时重新请求 URL 并热替换（见 11.4）。

**G8. 看番页会不会被 Header 的存储源逻辑覆盖？**  
不会，`rootPathAction` 显式跳过 `/bangumi` 和 `/share`。

### H. Agent 与 SSE

**H1. 前端怎么接 Agent？**  
REST 建会话/发消息，SSE 订阅事件；模块级单例保存会话 ID、消息、`lastSeq`；抽屉 UI 渲染。

**H2. 为什么用 SSE 不用 WebSocket？**  
单向推送、HTTP 基础设施友好、实现简单。WebSocket 适合双向高频交互；这里客户端发消息走普通 POST 就够。

**H3. EventSource 不能带 header 怎么办？**  
token 放 query（`?token=...`）；代价是日志泄漏风险；替代方案是 cookie 鉴权或短期 ticket。

**H4. 为什么不能依赖原生重连？**  
原生重连会复用旧 URL，`since` 不更新，导致重复/漏事件；必须 close 后用当前 `lastSeq` 重建。

**H5. `since` 和 `seq` 的语义？**  
后端事件日志 seq 从 0 单调递增；`since` 排他，只补 `seq > since`；前端 `lastSeq` 记录已处理的最大 seq，重复事件丢弃。

**H6. 断线重连流程？**  
onerror → close → 1/2/4s 退避重连 → 3 次后 diagnose → 40400 新建会话，其他 failed。

**H7. 50000 是什么？**  
后端未配置模型 key；前端 `enabled=false`，展示空态，不发消息。

**H8. 乐观 UI 怎么避免重复气泡？**  
用户消息先 pending，回显按文本匹配；工具卡片按 `callId` upsert。文本匹配有歧义，理想是 clientMessageId。

**H9. 为什么状态放模块单例？**  
抽屉关闭后流和消息要保留；组件卸载不能清状态。

**H10. 如何避免旧连接干扰新连接？**  
`if (es !== source) return`；每次连接前 `teardownStream()`。

**H11. SSE 部署要注意什么？**  
nginx 关闭 buffering、放宽 read timeout、不要压缩/缓存事件流；反向代理要支持长连接。

**H12. token 放 URL 安全吗？**  
不理想；日志/历史可能泄漏。短期 token、cookie 或一次性 ticket 更好。

### I. 性能

**I1. 首屏阻塞点在哪？**  
`/zfile.config.json` 请求完成后才 mount；之后布局再拉站点配置和存储源。配置接口慢会延迟白屏，但默认值保证不会挂。

**I2. 包体积问题？**  
PDF 2.41MB、3D 789KB、视频 722KB、文本 613KB；现代入口 714KB，legacy 入口 858KB（+162KB polyfills）。预览包已懒加载，但首次打开对应预览仍要下载。可进一步拆 manualChunks/按需加载。

**I3. 大目录渲染？**  
前端切片默认 1000，加载更多 50；表格虚拟化没做。超大目录应后端分页/虚拟列表。

**I4. 有哪些重复请求/竞态？**  
切存储源有 stale guard；目录配置和文件列表是两次请求；布局/页面都可能触发配置加载，需要避免重复。上传队列和 Agent 流是长生命周期，要注意泄漏。

**I5. 内存泄漏风险？**  
全局 keydown 监听、`setInterval` 轮询、EventSource、`useStorage`；组件卸载要清理（RSS 总览有 `onUnmounted(clearInterval)`，Agent 有 `dispose()`）。

### J. 反思与改进

**J1. 如果重做，你会改什么？**  
统一状态方案与重置；统一 API client/错误模型；修 typecheck + 补测试；把签名续期和 SSE 鉴权做对；拆包优化。

**J2. 最大的技术债？**  
三套请求/错误模型 + 两套状态机制 + 无测试。它们单独看都能工作，组合起来增加认知成本。

**J3. 你怎么做前端监控？**  
当前没有。可从三件事开始：全局 `window.onerror`/`unhandledrejection` 上报、接口错误率与耗时、关键路径埋点（上传成功率/SSE 重连次数）。

**J4. 你从项目里学到什么？**  
读成熟代码的能力、边界隔离（游客/登录、三后端）、长连接状态机、以及“能跑”和“可维护”之间的差距。

---

## 20. 压力问题与回答策略

### 20.1 “这不就是拿开源项目换皮吗？”

> 主体确实是 ZFile，我不回避。我的增量有三块：Agent 前端 786 行、公开看番页 329 行、RSS 后台与部署集成。更重要的是我吃透了它的路由、请求、权限、状态模型，才能在不破坏原有功能的前提下接入三个新后端。如果岗位要求从零造框架，这段经历的说服力会弱一些；如果要求在成熟系统上做增量，这正好是真实场景。

### 20.2 “为什么没有测试？”

> 这是明确的短板。当前只有 `pnpm build` 和手工回归。我补测试的顺序是：纯函数单测 → Agent 事件处理单测 → Playwright 黄金路径。不会说“项目简单所以不需要测试”。

### 20.3 “typecheck 都是坏的，还敢上线？”

> typecheck 坏是工具链版本不兼容（vue-tsc 1.6.5 / TS 5.7），不是类型错误本身。当前用 build 做门禁，但我知道这不够；正确做法是修工具链并放进 CI。

### 20.4 “前端权限有什么用？改个 JS 不就绕过了？”

> 对，前端权限只是 UX，不是安全边界。真正的权限在后端每个目录的配置和接口校验里；前端隐藏按钮只是减少误操作。这是我的明确认知，不是设计缺陷的辩解。

### 20.5 “分享密码放 URL 不是泄漏吗？”

> 是权衡，不是最佳实践。好处是下载/刷新不断链；风险是历史、日志、Referer。更好的方案是短期 share token 或 POST 换 cookie。当前场景是内网个人分享，风险可接受，但我会在公网场景改掉。

### 20.6 “记住密码明文存 localStorage？”

> 同样是体验优先的取舍，不安全。XSS 能直接读。重做会改成短期 token 或加密 + 更短有效期。面试官如果继续追，承认这是上游设计，我知道风险。

### 20.7 “自定义 JS 注入不就是后门？”

> 这是管理员配置能力，等于信任管理员。公网部署必须限制后台权限和配置写入。它不是我的设计，但我了解风险面。

### 20.8 “SSE 为什么不用 WebSocket？”

> 需求是服务端单向推事件，客户端发消息走 POST；SSE 更简单、过代理更友好。代价是不能带 header、原生重连不可靠，所以才有 token 放 query 和手动重连。如果未来需要双向高频交互，会换 WebSocket。

### 20.9 “上传断点续传都没有，可靠性怎么保证？”

> 只有 OneDrive 做了块级续传，其他策略中断后整文件重传。这在个人 NAS/内网可接受；公网大文件场景需要哈希分片、断点清单、服务端合并，当前没有。我不会把它包装成“高可靠上传”。

### 20.10 “状态管理为什么这么乱？”

> 两套机制确实增加认知成本。Pinia 管跨页面配置/列表，模块单例管长生命周期运行时状态。它解决了“组件卸载后流不能断”的实际问题，但不是最优雅的方案。重做会统一成 Pinia setup store + 明确 reset。

### 20.11 “首屏主包 714KB（legacy 858KB），你怎么优化？”

> 先做体积分析：PDF/3D/视频/文本都是懒加载，主包里大头是 Element Plus 和业务公共代码。优化顺序：manualChunks 拆公共依赖、检查重复引入、按需注册 Element Plus、评估是否还需要 legacy 构建。不会为了数字牺牲预览能力。

### 20.12 “如果明天让你重构，你先做什么？”

> 先修工具链（typecheck/CI），再统一请求层和状态重置，最后才动 UI。没有质量门禁的重构风险最高。

---

## 21. Demo 脚本

### 21.1 5 分钟核心演示

1. 打开首页：说明 URL 结构 `/:storageKey/:fullpath`，切换存储源、进目录、刷新不丢状态。
2. 表格/卡片切换、排序、右键菜单、快捷键选择。
3. 打开一个视频/图片/PDF：说明预览分发和懒加载。
4. 打开上传框：拖入多个文件，展示队列、并发、进度、取消。
5. 打开分享页：展示密码验证和文件列表。
6. 打开 `/bangumi`：无登录游客视角，播放一集。
7. 打开 Agent 抽屉：提问、展示工具卡片、停止、断线状态。

### 21.2 15 分钟完整演示

在 5 分钟基础上补：

- 管理后台：存储源配置、权限位、站点设置（自定义后缀/公告）。
- RSS 后台：总览状态轮询、订阅增删启停、追番设置。
- Agent：新建会话、旧会话失效提示、SSE 重连（可在 devtools 断网模拟）。
- 构建：`pnpm build` 产物与懒加载 chunk。
- 代码走读：`useFileData.loadFile` 的 stale guard、`useAgentChat.connect` 的重连、`useFileUpload` 的四策略分发。

### 21.3 Demo 前置条件

- 主站 8080 已启动；RSS 7892 可选（没有时 RSS 页面会报错但不影响文件站）。
- `local` 存储源存在，`/Bangumi` 下有视频。
- 浏览器 devtools Network 面板用于展示 SSE 流和上传请求。
- 不建议现场演示真实大文件上传（网络不可控），可准备小文件或截图。

---

## 22. 简历 bullet 与 STAR

### 22.1 简历 bullet（按岗位选 3–4 条）

- 在 ZFile（Vue 3 + Vite + Element Plus）前端上完成二次开发，接入 Agent、公开看番页与 AutoBangumi 管理模块，覆盖文件浏览、上传、预览、分享、权限全链路。
- 设计并实现 Agent 聊天前端：EventSource + `since` 排他重放 + `seq` 去重 + 指数退避重连 + 40400 会话自愈，支持工具调用卡片与乐观 UI。
- 实现游客只读的公开看番页：独立 axios 隔离登录态、后端 guest 授权、共享 Artplayer 播放器，避免 token 泄漏与错误跳登录。
- 集成四种上传策略（代理、S3 预签名、OneDrive 100MB 分片、又拍云签名表单），实现并发队列、进度、取消与重试。
- 完成 Docker/nginx 部署集成：`/rss-api` 反代、SSE buffering 关闭、Vite 开发代理与生产映射一致。

### 22.2 STAR：Agent 前端

- **S（情境）**：后端 Agent loop 已完成，但前端没有实时展示，用户只能等最终结果。
- **T（任务）**：在现有文件站里加入流式对话，要求断线可恢复、工具调用可见、不能污染原有登录态。
- **A（行动）**：选 SSE；设计 `since/seq` 协议；EventSource 手动重连；40400 自愈；工具卡片 upsert；模块级单例保活；nginx 关闭 buffering。
- **R（结果）**：抽屉关闭/重开不丢消息；后端重启后自动新建会话；工具调用有运行/成功/失败状态；与 mini-harness 的事件日志语义对齐。

### 22.3 STAR：公开看番页

- **S**：希望不登录也能看番，但本地浏览器可能存着管理员 token。
- **T**：做完全游客视角的只读页面，不能误用登录态，不能 42000 跳登录。
- **A**：独立 axios 不读 token；后端 guest 行授权；Header/Agent 隔离；共享播放器。
- **R**：同一浏览器登录管理员后打开 `/bangumi` 仍是游客权限；接口失败只显示页面错误，不跳登录。

---

## 23. 反问面试官

1. 团队目前的前端质量门禁是什么？typecheck、单测、E2E、CI 分别覆盖到什么程度？
2. 这个岗位更偏业务交付还是基础设施/组件库？
3. 团队如何做前后端协议设计？有没有 OpenAPI/类型生成？
4. 线上问题如何定位？有没有前端监控和 Source Map 上传？
5. 老项目迁移（Vue 2 → Vue 3、JS → TS）通常怎么排期？
6. 对 AI 功能的前端交互有没有既定规范（流式、工具调用、取消）？

---

## 24. 红线：不要吹的十件事

1. 不要说“从零写了 23k 行”——主体是 ZFile。
2. 不要说“有完善测试”——没有前端测试框架。
3. 不要说“typecheck 通过”——当前不可用。
4. 不要说“前端权限保证安全”——只是 UX。
5. 不要说“上传支持断点续传”——只有 OneDrive 块级续传。
6. 不要说“SSE 协议是我设计的”——协议是后端 mini-harness 的，前端做的是消费与重连。
7. 不要说“分享密码方案很安全”——URL query 有泄漏面。
8. 不要说“状态管理架构很清晰”——两套机制并存是技术债。
9. 不要说“支持高并发/大规模”——没有压测，定位是个人 NAS。
10. 不要把上游的 4 种上传/多类预览说成自己实现；说“理解并维护/扩展”。

---

## 25. 代码地图

### 25.1 启动与路由

| 位置 | 内容 |
| --- | --- |
| `src/main.ts:16-20` | 运行时配置加载后挂载 |
| `src/App.vue:19-26` | `isRouterAlive` + `provide('reload')` |
| `src/modules/router.ts:6-19` | 手写 `/` 与 `/:storageKey/:fullpath(.*)*` |
| `src/modules/router.ts:22-32` | `/login/:entry`、`/admin` 重定向 |
| `presets/tov.ts:47-55` | 文件路由排除 `file.vue` |
| `src/layouts/file.vue:41-76` | 站点配置、安装/游客跳转、自定义后缀 |
| `src/layouts/admin.vue` | 后台侧边栏与导航分组 |

### 25.2 请求与状态

| 位置 | 内容 |
| --- | --- |
| `src/http/index.js:17-32` | token、`axios-request`/`axios-from` |
| `src/http/index.js:44-65` | 信封拆解、`showDefaultMsg`/`responseIntercept` |
| `src/http/index.js:66-148` | 41000/42000/30000/2000* 错误分支 |
| `src/http/request.js:11-30` | method 包装（不支持 PATCH） |
| `src/http/watch.js:5-19` | 游客只读实例 |
| `src/http/rss.js:3-10` | RSS 实例、`/rss-api/v1` |
| `src/stores/global-config.ts:87-111` | `serverAddress`、响应式后台配置 |
| `src/stores/storage-config.ts:74-104` | 20 个权限位组合 |
| `src/stores/file-data.ts:44-68` | 文件列表切片、图标、预览标志 |

### 25.3 文件主链路

| 位置 | 内容 |
| --- | --- |
| `src/composables/file/useFileData.js:80-159` | `loadFile` 全流程 |
| `src/composables/file/useFileData.js:96-106` | storageKey 竞态保护 |
| `src/composables/file/useFileData.js:111-118` | `BACK` 行 |
| `src/composables/file/useFileData.js:150-157` | 41020/41021 密码处理 |
| `src/composables/file/useFileData.js:182-231` | `openRow` 预览/进目录 |
| `src/composables/file/useFilePwd.js:8-9` | 两份密码缓存 |
| `src/composables/file/useFilePwd.js:92-122` | minimatch 路径匹配 |
| `src/composables/file/useTableOperator.js:34-46` | 快捷键 |
| `src/composables/header/useHeaderStorageList.js:59-89` | 根路径/分享/看番分流 |
| `src/components/file/view/TableFileView.vue` | 表格视图 |
| `src/components/file/view/CardFileView.vue` | 卡片视图 |

### 25.4 上传与预览

| 位置 | 内容 |
| --- | --- |
| `src/composables/file/useFileUpload.js:494-500` | 并发闸门 |
| `src/composables/file/useFileUpload.js:538-545` | 四种上传策略分发 |
| `src/composables/file/useFileUpload.js:590-619` | PROXY |
| `src/composables/file/useFileUpload.js:623-654` | S3 |
| `src/composables/file/useFileUpload.js:657-727` | OneDrive 分片 |
| `src/composables/file/useFileUpload.js:730-749` | UPYUN |
| `src/components/file/ZUpload.vue` | 上传对话框与进度 UI |
| `src/components/file/preview/VideoPlayer.vue:122-124` | 播放器偏好持久化 |
| `src/components/file/preview/VideoPlayer.vue:175-217` | FLV/HLS 适配 |
| `src/components/file/preview/VideoPlayer.vue:275-310` | 弹幕/字幕 |
| `src/components/file/preview/VideoPlayer.vue:353-406` | 连播与外部播放器 |
| `src/utils/models/path.ts:72-107` | kkfileview URL |

### 25.5 分享与看番

| 位置 | 内容 |
| --- | --- |
| `src/pages/share/[shareKey].vue:131-161` | 分享密码验证、密码写 URL |
| `src/composables/share/useShareData.js:59-119` | 分享文件加载、目录密码、权限 |
| `src/composables/share/useShareData.js:129-163` | `initShare` |
| `src/pages/bangumi.vue:115-154` | 目录加载、fileDataStore 灌入、游客配置 |
| `src/api/watch.js:4` | `WATCH_STORAGE_KEY = 'local'` |
| `src/api/watch.js:21-29` | 游客文件/配置接口 |
| `src/components/layout/Header.vue:6-9` | AutoBangumi 入口 |
| `src/components/layout/Header.vue:121` | 看番/分享页隐藏存储源选择 |
| `src/components/layout/Header.vue:288-340` | 自定义 CSS/JS 注入 |
| `src/pages/admin/rss/index.vue:48-52` | 状态 5 秒轮询 |
| `src/pages/admin/rss/setting.vue:60-84` | 配置读取/保存 |

### 25.6 Agent

| 位置 | 内容 |
| --- | --- |
| `src/api/home/agent.js` | 6 个 REST 接口 + SSE URL |
| `src/composables/agent/useAgentChat.js:143-215` | SSE 事件处理与去重 |
| `src/composables/agent/useAgentChat.js:224-243` | diagnose（40400 自愈） |
| `src/composables/agent/useAgentChat.js:245-281` | EventSource 连接与退避重连 |
| `src/composables/agent/useAgentChat.js:300-315` | 乐观发送与失败标记 |
| `src/composables/agent/useAgentChat.js:326-355` | 新建会话与旧会话清理 |
| `src/components/agent/AgentAssistant.vue:197-203` | 只在登录且非分享/看番页显示 |
| `src/components/agent/AgentAssistant.vue:277` | 中文输入法 Enter 防误发 |
| `src/layouts/file.vue:16` | Agent 挂载点 |
| `vite.config.ts` `/api` 代理 | 开发期 SSE/接口转发 |

---

## 26. 30 分钟前检查清单

- [ ] 能用一句话说清“主体是 ZFile，我做了哪三块”。
- [ ] 能画出三层架构（页面/组件 → composable/store → api/http → 三后端）。
- [ ] 能讲完整 `loadFile` 链路，包括 stale guard 和 BACK 行。
- [ ] 能讲四种上传策略的差异，至少记住 S3 的 `Content-Type` 和 OneDrive 的 202。
- [ ] 能讲 Agent 的 `since/seq`、手动重连、40400/50000。
- [ ] 能讲游客看番页的隔离手段（独立 axios、guest 行、Header/Agent 隐藏）。
- [ ] 能主动说出三个短板：无测试、typecheck 坏、前端权限非安全边界。
- [ ] 能说出构建数字：3,970 modules / 55.62s / 最大 chunk PDF 2.41MB。
- [ ] 准备 1 个失败/踩坑故事（例如 SSE 重连、上传 CORS、路径编码）。
- [ ] 准备 2 个反问面试官的问题。

---

## 附：一分钟自检表（面试前默念）

1. **边界**：游客 vs 登录、三后端、两套状态。
2. **竞态**：storageKey stale guard、SSE seq 去重、上传队列补位。
3. **权衡**：运行时配置、URL 状态、前端权限、密码缓存。
4. **诚实**：不认领上游代码，不吹测试和安全。
5. **闭环**：任何设计都能说出“为什么、代价、如果重做怎么改”。
