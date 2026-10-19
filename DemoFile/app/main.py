from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.auth import read_token
from app.core.context import new_trace_id, set_current_user_id, set_request_info
from app.core.exception_handlers import register_exception_handlers
from app.models.user import ANONYMOUS_ID
from app.agent.host import agent_host
from app.modules.agent.router import router as agent_router
from app.modules.config.router import router as site_router
from app.modules.front.router import STATIC_DIR, router as front_router
from app.modules.install.router import router as install_router
from app.modules.storage.router import router as storage_router
from app.modules.user.router import router as user_router
from app.storage.loader import load_storage_sources
from app.modules.storage.proxy_router import router as proxy_router


class TraceMiddleware:
    """ASGI 中间件。使用 ASGI 而非 BaseHTTPMiddleware，避免下游连接中断。"""
    def __init__(self,app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            new_trace_id()

            # HTTP 头为 [(b"name", b"value")] 列表，转成小写键的字符串字典后取值。
            headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}

            # 登录态：有 zfile-token 则 read_token()，否则使用 ANONYMOUS_ID。
            # 这是 current_user_id 的唯一写入点：同步依赖运行在线程池的 context
            # 副本上，set 的值传不出去；存储层通过 contextvar 读取当前用户，
            # 因此必须在中间件写入。
            token = headers.get("zfile-token")
            login_id = read_token(token) if token else None
            set_current_user_id(login_id if login_id is not None else ANONYMOUS_ID)

            # 请求来源：供 AbstractProxyTransferService._get_base_url() 拼 /pd/ 下载地址。
            set_request_info(
                axios_from=headers.get("axios-from"),
                base_url=_build_base_url(scope,headers)
            )
            
        await self.app(scope, receive,send)


def _build_base_url(scope: dict, headers: dict[str, str]) -> str | None:
    """当前请求的后端地址，形如 "http://127.0.0.1:8080"。

    对应 Java 的 RequestHolder.getRequestServerAddress()。
    scheme 优先取 X-Forwarded-Proto，其次 scope["scheme"]；host/port 依次取
    X-Forwarded-Host / X-Forwarded-Port、Host 头（可能自带端口）、scope["server"]。
    协议默认端口（http=80 / https=443）不拼入结果。
    """
    forwarded_proto = headers.get("x-forwarded-proto")
    forwarded_port = headers.get("x-forwarded-port")
    host_header = headers.get("x-forwarded-host") or headers.get("host")

    scheme = forwarded_proto or scope["scheme"]

    if host_header:
        server_name, _, host_port = host_header.partition(":")
        # Host 头自带的端口仅在 X-Forwarded-Port 缺席时使用（与 Java 顺序一致）。
        if host_port and not forwarded_port:
            forwarded_port = host_port
    else:
        server = scope.get("server")
        server_name = server[0] if server else None

    if forwarded_port:
        port = forwarded_port
    elif forwarded_proto:
        # 有转发协议但没有转发端口时按协议默认端口推定，避免使用代理到后端的内部 socket 端口。
        port = "443" if forwarded_proto.lower() == "https" else "80"
    else:
        server = scope.get("server")
        port = str(server[1]) if server else None

    # 默认端口不写入地址（http:80 / https:443）。
    if (port == "443" and scheme.lower() == "https") or (port == "80" and scheme.lower() == "http"):
        port = None

    if not server_name:
        return None
    return f"{scheme}://{server_name}" + (f":{port}" if port else "")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动装配：读取数据库中的所有存储源，逐个初始化、测试连接并注册。
    # 启动期没有请求要处理，同步阻塞调用可直接执行。
    load_storage_sources()
    # Agent 宿主：缺少 DEEPSEEK_API_KEY 时记录日志并跳过，不影响站点启动。
    await agent_host.start()
    yield
    await agent_host.stop()


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
app.include_router(agent_router, prefix="/api")
app.include_router(proxy_router)

# 前端静态产物（与 Java file:static/ 相同的外置目录，相对 CWD）。
# check_dir=False：static/ 尚未构建或拷贝时也能启动。
app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets", check_dir=False), name="assets")

# 前端路由与 SPA 回退必须最后注册：内部 catch-all 需要位于路由表末尾。
app.include_router(front_router)
