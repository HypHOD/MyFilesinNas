import logging
import os
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from module.api import v1
from module.api.health import router as health_router
from module.conf import VERSION, settings, setup_logger
from module.core import AppContext

setup_logger(settings.log.debug_enable)
logger = logging.getLogger(__name__)

uvicorn_logging_config = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": logger.handlers,
    "loggers": {
        "uvicorn": {"level": logger.level},
        "uvicorn.access": {"level": "WARNING"},
    },
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    ctx: AppContext = app.state.ctx
    # 迁移/建表在开始服务前完成；失败则中止启动（loud fail）
    await ctx.startup()
    # 首次运行（配置全默认）不自动启动循环，等用户完成配置后手动启动
    if not ctx.first_run_boot:
        # start_tasks() 自身把「等待下载器 + 启动循环」作为受监督的后台任务
        # 拉起后立即返回，不阻塞服务器启动
        await ctx.start_tasks()
    yield
    # 关闭
    await ctx.stop()


def create_app() -> FastAPI:
    ctx = AppContext.build(settings)
    app = FastAPI(lifespan=lifespan)
    app.state.ctx = ctx

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["*"],
    )

    # API 路由挂在 /api 下
    app.include_router(v1, prefix="/api")

    # 无鉴权存活探针挂在应用根路径，供容器/orchestrator 健康检查
    app.include_router(health_router)

    return app


app = create_app()


@app.get("/", status_code=302, tags=["html"])
def index():
    return RedirectResponse("/docs")


if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    uvicorn.run(
        app,
        host=host,
        port=settings.program.webui_port,
        log_config=uvicorn_logging_config,
    )
