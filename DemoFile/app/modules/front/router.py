"""前端静态托管 + SPA 回退。

对应 Java FrontIndexController.java 与 GlobalExceptionHandler 的 NoResourceFound 分支。

前端构建产物（zfile-react 的 dist/）拷贝到进程外的 static/ 目录，对应 Java 的
spring.web.resources.static-locations=file:static/（application.properties:14）。
后端以同源方式同时提供 API 和页面，生产环境不需要 nginx。产物外置的收益是升级
前端只需替换目录并刷新浏览器，无需重建或重启后端。

核心问题是 history 路由的 URL：用户在 /local/我的文档 刷新时，浏览器把 URL 原样
发给服务器，而该路径只有前端 router 认识。服务器需要把不认识的路径统一回
index.html，由前端 router 重新解释，这就是 SPA 回退。

Java 对照：
    FrontIndexController.java:39-95      "/" 映射：读取 static/index.html
    GlobalExceptionHandler.java:139-143  NoResourceFoundException → index.html
    GlobalExceptionHandler.java:115-130  NotFoundAccessException：isAxiosRequest() 分支

挂载顺序（main.py）：
    app.mount("/assets", StaticFiles(...))    必须在 include_router 之前
    app.include_router(front_router)          含 catch-all，必须位于最后
路由按注册顺序匹配；mount 过晚会导致 /assets/*.js 被 catch-all 当成 index.html。

端点约定：
  GET /zfile.config.json → {"baseUrl": ""}
      空串表示相对地址、永远同源（zfile-vue 生产环境惯例值）。开发期该请求由
      vite 的 public/ 拷贝应答（值为 8080），不会到后端。响应直接是 dict，
      不是业务 API，不使用信封。
  GET /favicon.svg → FileResponse(STATIC_DIR / "favicon.svg")
      不存在 → PlainTextResponse(..., 404)。图标请求不带 axios-request 头，
      若落入 catch-all 会被当作导航返回 index.html，浏览器静默忽略。
  GET /{full_path:path}（catch-all，include_in_schema=False）
      带 axios-request 头 → XHR 请求了不存在的接口，返回 404 JSON 信封
      （Java 的 NoResourceFound 分支不区分来源；这里按请求头区分，避免调试时
      拿到 HTML）。否则视为浏览器导航，返回 index.html；"/" 也落在 catch-all
      （full_path == ""）。

实现约束：
  - async def：这里没有 DB / registry 等同步阻塞调用（proxy_router 的 sync def
    是相反场景），FileResponse 可直接返回。
  - 不加返回类型注解：返回多种 Response 对象，不使用 response_model 机制。
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
    # SPA 启动配置。前端渲染前 fetch('/zfile.config.json')（src/config.ts 的
    # loadConfig），用 baseUrl 决定 axios 请求地址。开发期由 vite 的 public/ 拷贝
    # 应答；同源部署后由这里应答。空串表示相对地址、永远同源。
    return {"baseUrl": ""}


@router.get("/favicon.svg", include_in_schema=False)
async def favicon():
    # 浏览器标签页图标。该请求不带 axios-request 头；若不单独处理，会被 catch-all
    # 当作导航返回 index.html，浏览器静默忽略，图标损坏时难以定位原因。
    favicon_path = STATIC_DIR / "favicon.svg"
    if not favicon_path.is_file():
        return PlainTextResponse("static favicon.svg not found", status_code=404)
    return FileResponse(favicon_path)


@router.get("/{full_path:path}", include_in_schema=False)
async def spa_fallback(full_path: str, request: Request):
    # 所有 GET 的兜底（首页 "/" 也落在这里）。浏览器直发 /local/xxx（刷新/直达）时
    # 服务器不认识该路径，统一回 index.html 交给前端 router 重新解释，这是 history
    # 路由刷新不 404 的原因。分流：带 axios-request 头（XHR 打到不存在的接口，
    # 属于代码 bug）→ JSON 404；否则 → index.html。

    # Java 的 NoResourceFound 一律回 HTML；这里按请求头区分，避免调试时拿到 HTML。
    if request.headers.get("axios-request"):
        return JSONResponse(
            status_code=404,
            content=error(ErrorCode.BIZ_NOT_FOUND.code, ErrorCode.BIZ_NOT_FOUND.msg).model_dump(),
        )

    # 浏览器导航（地址栏/刷新/前进后退）：history 路由的 URL 只有前端认识，统一回 index.html。
    index = STATIC_DIR / "index.html"
    if not index.is_file():
        return PlainTextResponse("static index.html not found", status_code=404)
    return FileResponse(index)
