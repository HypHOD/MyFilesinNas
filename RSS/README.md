# RSS — Auto_Bangumi 复现

从零复现 [Auto_Bangumi](https://github.com/EstrellaXD/Auto_Bangumi) 的学习项目：RSS 自动追番 → 自动下载 → 重命名成 Plex/Jellyfin 友好的目录结构。

## 技术栈

- 后端：Python 3.13 + FastAPI + SQLModel（异步 SQLite / WAL），uv 管理依赖
- 前端：Vue 3 + TypeScript + Vite + naive-ui + Pinia

## 进度

**阶段 0 —— 骨架（当前）**

- [x] 配置系统（`config/config.json` 读写 + 热重载）
- [x] 异步数据库层（bangumi / rssitem / torrent 三表 + repo 模式）
- [x] 周期任务调度器（PeriodicTask / Scheduler）+ 组合根 AppContext
- [x] REST API：health / program 启停 / config / rss / bangumi
- [x] Vue3 前端脚手架（Dashboard / RSS / 番剧 / 设置）

**后续**

- [ ] 阶段 1：RSS 拉取 → 标题解析 → 下载器（qB/mock）→ 轮询重命名（最小闭环）
- [ ] 阶段 2：TMDB 海报、通知、登录认证、过滤规则、季/集偏移
- [ ] 阶段 3：aria2 支持、LLM 标题解析、Schema 迁移系统、Docker 部署

## 开发运行

### 后端（端口 7892，API 文档 `/docs`）

```bash
cd backend && uv sync
cd src && uv run python main.py
```

运行目录是 `backend/src`，运行时的 `config/` 与 `data/` 会生成在该目录下（已 gitignore）。

### 测试

```bash
cd backend && uv run pytest
```

### 前端（端口 5173，`/api`、`/health` 代理到 7892）

```bash
cd webui && pnpm install
pnpm dev
```
