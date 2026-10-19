from contextvars import ContextVar
from uuid import uuid4

_trace_id: ContextVar[str] = ContextVar("trace_id", default="")

def new_trace_id() -> str:
    trace_id = uuid4().hex
    _trace_id.set(trace_id)
    return trace_id

def get_trace_id() -> str:
    return _trace_id.get()


# 当前用户 id（ContextVar）
#
# auth.get_current_user_id 是 FastAPI 依赖，仅限路由使用；存储层等非路由代码
# 通过本模块读取。
#
# 注意：FastAPI 会把同步依赖/同步端点放入线程池执行，线程池运行的是 context
# 副本，在同步依赖里 set 的值无法传回调用方。因此写入该值的依赖必须写成
# async def（或改用 ASGI 中间件）。
_current_user_id: ContextVar[int | None] = ContextVar("current_user_id", default=None)

def set_current_user_id(user_id: int | None) -> None:
    _current_user_id.set(user_id)

def get_current_user_id() -> int | None:
    """None = 不在请求上下文里（启动期），调用方自己决定兜底成谁。"""
    return _current_user_id.get()


# ── 请求来源信息（拼下载地址时使用）────────────────────────────────────
#
# 对应 Java 的 RequestHolder（ThreadLocal 保存 HttpServletRequest）。
# AbstractProxyTransferService._get_base_url() 在拼 /pd/ 下载地址前需要当前请求
# 的域名。与 current_user_id 相同，写入点只在中间件（原因见上）。
_axios_from: ContextVar[str | None] = ContextVar("axios_from", default=None)
_request_base_url: ContextVar[str | None] = ContextVar("request_base_url", default=None)


def set_request_info(axios_from: str | None, base_url: str | None) -> None:
    _axios_from.set(axios_from)
    _request_base_url.set(base_url)


def get_axios_from() -> str | None:
    """前端每个请求都带的 axios-from 头（= zfile.config.json 里的 baseUrl）。"""
    return _axios_from.get()


def get_request_base_url() -> str | None:
    """请求自己的地址（如 http://127.0.0.1:8080）。启动期没有请求 → None。"""
    return _request_base_url.get()

