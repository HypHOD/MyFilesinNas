import logging
import os
import signal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from module.conf import VERSION
from module.core import AppContext
from module.models import APIResponse

from .deps import get_context
from .response import u_response

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/program", tags=["program"])

# 说明：lifespan 的启停逻辑在 main.py；这里的 AppContext 按请求注入。
# 骨架阶段暂不挂鉴权依赖，阶段 2 加登录后为这些端点补上 get_current_user。


@router.post("/restart", response_model=APIResponse)
async def restart(ctx: AppContext = Depends(get_context)):
    try:
        resp = await ctx.restart()
        return u_response(resp)
    except Exception as e:
        logger.warning(f"Failed to restart program: {e}")
        raise HTTPException(
            status_code=500,
            detail={
                "msg_en": "Failed to restart program.",
                "msg_zh": "重启程序失败。",
            },
        )


@router.post("/start", response_model=APIResponse)
async def start(ctx: AppContext = Depends(get_context)):
    try:
        resp = await ctx.start_tasks()
        return u_response(resp)
    except Exception as e:
        logger.warning(f"Failed to start program: {e}")
        raise HTTPException(
            status_code=500,
            detail={
                "msg_en": "Failed to start program.",
                "msg_zh": "启动程序失败。",
            },
        )


@router.post("/stop", response_model=APIResponse)
async def stop(ctx: AppContext = Depends(get_context)):
    resp = await ctx.stop()
    return u_response(resp)


@router.get("/status", response_model=dict)
async def program_status(ctx: AppContext = Depends(get_context)):
    return {
        "status": ctx.is_running,
        "version": VERSION,
        "first_run": ctx.first_run,
    }


@router.post("/shutdown", response_model=APIResponse)
async def shutdown_program(ctx: AppContext = Depends(get_context)):
    await ctx.stop()
    logger.info("Shutting down program...")
    os.kill(os.getpid(), signal.SIGINT)
    return JSONResponse(
        status_code=200,
        content={
            "msg_en": "Shutdown program successfully.",
            "msg_zh": "关闭程序成功。",
        },
    )
