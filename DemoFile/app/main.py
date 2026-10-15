from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.auth import read_token
from app.core.context import new_trace_id, set_current_user_id, set_request_info
from app.core.exception_handlers import register_exception_handlers
from app.models.user import ANONYMOUS_ID
from app.modules.config.router import router as site_router
from app.modules.front.router import STATIC_DIR, router as front_router
from app.modules.install.router import router as install_router
from app.modules.storage.router import router as storage_router
from app.modules.user.router import router as user_router
from app.storage.loader import load_storage_sources
from app.modules.storage.proxy_router import router as proxy_router


class TraceMiddleware:
    '''ASGI中间件 不使用 BaseHTTPMiddleware 防止下游中断'''
    def __init__(self,app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            new_trace_id()

            # HTTP 头是 [(b"name", b"value")] 列表，转成 {小写名: 字符串} 方便取（机械活，写好了）
            headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}

            # TODO ① 登录态：有 zfile-token 就 read_token()，没有 / 查不到 → ANONYMOUS_ID，
            #          然后 set_current_user_id(...)
            #   这是"当前用户"唯一的写入点 —— 同步依赖在线程池里跑的是 context 副本，
            #   set 不出去；而存储层 get_current_user_base_path() 拿的是 contextvar，
            #   所以必须在这里写。
            token = headers.get("zfile-token")
            login_id = read_token(token) if token else None
            set_current_user_id(login_id if login_id is not None else ANONYMOUS_ID)

            # TODO ② 请求来源：set_request_info(axios_from=headers.get("axios-from"),
            #                                   base_url=_build_base_url(scope, headers))
            #   给 AbstractProxyTransferService._get_base_url() 用（拼 /pd/ 下载地址）。
            set_request_info(
                axios_from=headers.get("axios-from"),
                base_url=_build_base_url(scope,headers)
            )
            
        await self.app(scope, receive,send)


def _build_base_url(scope: dict, headers: dict[str, str]) -> str | None:
    """当前请求的后端地址，形如 "http://127.0.0.1:8080"。
    对应 Java 的 RequestHolder.getRequestServerAddress()。

    规则（照抄 Java）：
      - scheme：X-Forwarded-Proto 优先，其次 scope["scheme"]
      - host/port：X-Forwarded-Host / X-Forwarded-Port 优先；
        Host 头（可能自带 ":8080"）次之；最后 scope["server"]（是个 (host, port) 元组）
      - 端口是协议默认值（http=80 / https=443）时不拼端口

    TODO 写实现
    """
    # raise NotImplementedError
    forwarded_proto = headers.get("x-forwarded-proto")
    forwarded_port = headers.get("x-forwarded-port")
    host_header = headers.get("x-forwarded-host") or headers.get("host")

    scheme = forwarded_proto or scope["scheme"]

    if host_header:
        server_name, _, host_port = host_header.partition(":")
        # Host 头自带的端口只在 X-Forwarded-Port 缺席时算数（Java 的顺序）
        if host_port and not forwarded_port:
            forwarded_port = host_port
    else:
        server = scope.get("server")
        server_name = server[0] if server else None

    if forwarded_port:
        port = forwarded_port
    elif forwarded_proto:
        # 有转发协议但没转发端口 → 按协议默认端口推定（别退回代理→后端的内部 socket 端口）
        port = "443" if forwarded_proto.lower() == "https" else "80"
    else:
        server = scope.get("server")
        port = str(server[1]) if server else None

    # 默认端口不写出来（http:80 / https:443）
    if (port == "443" and scheme.lower() == "https") or (port == "80" and scheme.lower() == "http"):
        port = None

    if not server_name:
        return None
    return f"{scheme}://{server_name}" + (f":{port}" if port else "")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动装配：读 DB 里所有存储源 → 逐个 init + test_connection → 注册进 registry。
    # 同步阻塞调用放这里是合适的（启动期还没有请求要处理），别去 await to_thread。
    load_storage_sources()
    yield


app = FastAPI(
    title="ZFile",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    redoc_url=None,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["content-type", "zfile-token", "axios-request", "axios-from"],
)

app.add_middleware(TraceMiddleware)

register_exception_handlers(app)

app.include_router(install_router, prefix="/api")
app.include_router(site_router, prefix="/api")
app.include_router(user_router)
app.include_router(storage_router, prefix="/api")
app.include_router(proxy_router)

# 前端静态产物（与 Java file:static/ 同款外置目录，相对 CWD）
# check_dir=False：static/ 还不存在（没构建/拷贝）也能启动
app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets", check_dir=False), name="assets")

# 前端路由 + SPA 回退：★ 最后注册（内部 catch-all 必须垫底）
app.include_router(front_router)
