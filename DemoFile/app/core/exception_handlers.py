import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.errors import BizException, ErrorCode
from app.core.response import AjaxJson, error

logger = logging.getLogger(__name__)

def _json(ajax: AjaxJson, status_code: int) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=ajax.model_dump()
    )

def _field_name(err: dict) -> str:
    loc = [str(p) for p in err.get("loc",()) if p not in ("body","query", "path")]
    return ".".join(loc) or "unknow"

def register_exception_handlers(app: FastAPI) -> None:

    @app.exception_handler(BizException)
    async def handle_biz_exception(request: Request, exc: BizException) -> JSONResponse:
        return _json(
            error(exc.error_code.code,exc.msg),
            exc.http_status
        )

    @app.exception_handler(RequestValidationError) 
    async def handle_validation_error(request: Request, exc: RequestValidationError) ->JSONResponse:
        # 对应HTTP 400 + 41000 + {字段}
        field_errors = {_field_name(e): e["msg"] for e in exc.errors()}
        return _json(
            error(ErrorCode.BIZ_BAD_REQUEST.code,ErrorCode.BIZ_BAD_REQUEST.msg,field_errors),
            400,
        )

    @app.exception_handler(Exception)
    async def handle_unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("未处理异常: %s %s",request.method,request.url.path)
        return _json(error(ErrorCode.SYSTEM_ERROR.code, ErrorCode.SYSTEM_ERROR.msg), 500)
    
