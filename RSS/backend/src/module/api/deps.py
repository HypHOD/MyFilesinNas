"""API 路由共享的 FastAPI 依赖。"""

from fastapi import Request

from module.core import AppContext


def get_context(request: Request) -> AppContext:
    """取 lifespan 拥有的 AppContext（挂在 app.state 上）。"""
    return request.app.state.ctx
