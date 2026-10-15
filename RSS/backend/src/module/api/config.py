"""配置读写接口。

GET 对敏感字段（password/api_key/token/secret）打掩码；PATCH 时载荷中的
掩码值视为"未修改"，恢复为当前真实值后再落盘——避免把 ``********`` 字面
写进配置文件。
"""

import logging

from fastapi import APIRouter, Depends

from module.conf import settings
from module.core import AppContext
from module.models import Config

from .deps import get_context

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/config", tags=["config"])

_MASK = "********"
_SENSITIVE_KEYS = ("password", "api_key", "token", "secret")


def _is_sensitive(key: str) -> bool:
    return any(s in key.lower() for s in _SENSITIVE_KEYS)


def _mask(data: dict) -> dict:
    result: dict = {}
    for k, v in data.items():
        if isinstance(v, dict):
            result[k] = _mask(v)
        elif isinstance(v, str) and v and _is_sensitive(k):
            result[k] = _MASK
        else:
            result[k] = v
    return result


def _restore(data: dict, current: dict) -> dict:
    """把载荷中的掩码值（用户未修改）恢复为磁盘上的真实值。"""
    for k, v in data.items():
        if isinstance(v, dict) and isinstance(current.get(k), dict):
            data[k] = _restore(v, current[k])
        elif v == _MASK and _is_sensitive(k):
            data[k] = current.get(k, "")
    return data


@router.get("", response_model=dict)
async def get_config() -> dict:
    return _mask(settings.model_dump())


@router.patch("", response_model=dict)
async def update_config(data: Config, ctx: AppContext = Depends(get_context)):
    """整体更新配置：落盘后经 AppContext 热重载（调度器随之重启）。"""
    settings.save(_restore(data.model_dump(), settings.model_dump()))
    await ctx.reload_settings()
    return _mask(settings.model_dump())
