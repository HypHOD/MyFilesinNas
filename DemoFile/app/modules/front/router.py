"""前端静态托管 + SPA 回退 —— 对照 FrontIndexController.java + GlobalExceptionHandler 的 NoResourceFound 分支。

背景（这一步解决什么）：
  前端构建产物（zfile-react 的 dist/）拷贝到**进程外**的 static/ 目录 —— 对应 Java 的
  spring.web.resources.static-locations=file:static/（application.properties:14），
  由后端以"同源"方式服务：生产环境一个进程同时给 API 和页面，不需要 nginx。
  产物外置的红利：升级前端 = 换个目录、刷新浏览器，不用重新构建/重启后端。

  核心难点只有一个：history 路由的"假 URL"。用户在 /local/我的文档 按 F5，
  浏览器把当前 URL 原样发给服务器，而它只有前端 router 认识 —— 服务器必须把
  "不认识的路径"统一回 index.html，让前端 router 拿到页面后重新解释 URL。
  这就是 SPA 回退。

  对照答案：
    FrontIndexController.java:39-95      "/" 映射：读 static/index.html 返回
                                         （title/favicon 替换 + Cache-Control 是最小版不做的差异）
    GlobalExceptionHandler.java:139-143  NoResourceFoundException → index.html（回退本体）
    GlobalExceptionHandler.java:115-130  NotFoundAccessException：isAxiosRequest() 分支 ——
                                         catch-all 的蓝本：XHR 给 JSON，导航给 HTML

挂载方式（main.py 装配区，★ 顺序有讲究）：
    app.mount("/assets", StaticFiles(...))     ← 必须在 include_router 之前！
    app.include_router(front_router)           ← 含 catch-all，必须垫底
  路由按注册顺序匹配；mount 晚了，/assets/*.js 会被 catch-all 吞成 index.html。

---------------- 你要实现的逻辑（函数级规格） ----------------

STATIC_DIR = Path("static")
  - 相对 CWD —— 和 sqlite:///./zfile.db 同款约定（uvicorn 启动时 CWD 必须是 DemoFile/）
  - 内容 = pnpm build 产物，部署时从 zfile-react/dist 拷进来

GET /zfile.config.json → {"baseUrl": ""}
  - 空串 = 相对地址 = 永远同源（zfile-vue 生产环境的惯例值）
  - dev 期这个请求到不了后端：浏览器在 5173，vite 用 public/ 里的拷贝应答（值是 8080）
  - 响应直接是 dict，不用信封 —— 它不是业务 API，是启动配置

GET /favicon.svg → FileResponse(STATIC_DIR / "favicon.svg")
  - 不存在 → PlainTextResponse("static favicon.svg not found", 404)
  - 为什么不放它掉进 catch-all：图标请求不带 axios-request 头，会被当"导航"回
    index.html —— 浏览器静默忽略，图标坏了但看不出原因

GET /{full_path:path}（catch-all，include_in_schema=False）
  ① request.headers.get("axios-request") 非空 → XHR 打到了不存在的接口：
       JSONResponse(status_code=404,
                    content=error(ErrorCode.BIZ_NOT_FOUND.code,
                                  ErrorCode.BIZ_NOT_FOUND.msg).model_dump())
     —— 对照 Java NotFoundAccessException 的 axios 分支（@ResponseStatus(404) + 信封）
     需要先往 core/errors.py 加一行（抄 Java ErrorCode:28）：
         BIZ_NOT_FOUND = ("40400", "NOT FOUND")
     ★ 相对 Java 的刻意改进（写进代码注释）：它的 NoResourceFound 分支一律回 HTML、
       不区分来源；我们按头区分 —— XHR 打错接口是代码 bug，喂 HTML 只会让调试变难。
  ② 否则 → 浏览器导航（地址栏 / 刷新 / 前进后退）→ FileResponse(STATIC_DIR / "index.html")
     不存在 → PlainTextResponse("static index.html not found", 404)（对照 FrontIndexController:94）
  ③ "/" 也落在 catch-all（full_path == ""）→ 首页，Java 的 "/" 是单独映射，我们合二为一

两个实现纪律：
  - async def：这里没有 DB / registry 这类同步阻塞调用（与 proxy_router 走线程池的
    sync def 相反的场景），FileResponse 在 async 处理器里直接返回即可
  - 不加返回类型注解（同 proxy_router）：返回的是多种 Response 对象，
    不使用 FastAPI 的 response_model 机制
"""

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse

from app.core.errors import ErrorCode
from app.core.response import error

STATIC_DIR = Path("static")

router = APIRouter(tags=["front"])


@router.get("/zfile.config.json", include_in_schema=False)
async def zfile_config():
    # 用途：SPA 的启动配置。zfile-react 在渲染前会 fetch('/zfile.config.json')
    #   （src/config.ts 的 loadConfig），拿 baseUrl 决定 axios 请求发到哪。
    #   dev 期（5173）被 vite 的 public/ 拷贝应答，到不了这里；同源部署后由这里应答。
    # 空串 = 相对地址 = 永远同源
    return {"baseUrl": ""}


@router.get("/favicon.svg", include_in_schema=False)
async def favicon():
    # 用途：浏览器标签页图标。注意它不带 axios-request 头 —— 若不单独处理，
    #   会被 catch-all 当"导航"喂回 index.html，浏览器静默忽略，图标坏了无从排查。
    favicon_path = STATIC_DIR / "favicon.svg"
    if not favicon_path.is_file():
        return PlainTextResponse("static favicon.svg not found", status_code=404)
    return FileResponse(favicon_path)


@router.get("/{full_path:path}", include_in_schema=False)
async def spa_fallback(full_path: str, request: Request):
    # 用途：所有 GET 的兜底（首页 "/" 也落这里）。服务器侧接住 "history 路由假 URL" 的点：
    #   浏览器直发 /local/xxx（刷新/直达）时服务器不认识，统一回 index.html 交给前端 router
    #   重新解释 URL —— 这是 React Router 的 browser history 能刷新不 404 的原因。
    #   分流：带 axios-request 头（XHR 打到不存在的接口 = 代码 bug）→ JSON 404；否则 → index.html。

    # XHR 打错的接口给 JSON 404（★ 相对 Java 的改进：它的 NoResourceFound 一律回 HTML）
    if request.headers.get("axios-request"):
        return JSONResponse(
            status_code=404,
            content=error(ErrorCode.BIZ_NOT_FOUND.code, ErrorCode.BIZ_NOT_FOUND.msg).model_dump(),
        )

    # 浏览器导航（地址栏/刷新/前进后退）：history 路由的 URL 只有前端认识，统一回 index.html
    index = STATIC_DIR / "index.html"
    if not index.is_file():
        return PlainTextResponse("static index.html not found", status_code=404)
    return FileResponse(index)
