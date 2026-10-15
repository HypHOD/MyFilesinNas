from typing import Any, Generic, TypeVar
from pydantic import BaseModel
from app.core.context import get_trace_id

CODE_SUCCESS = "0"
T = TypeVar("T")

class AjaxJson(BaseModel,Generic[T]):
    code: str
    msg:str|None = None
    data: T| None = None
    dataCount: int | None = None
    traceId: str = ""

def success(msg: str = "ok") -> AjaxJson:
    return AjaxJson(
        code=CODE_SUCCESS,
        msg=msg,
        traceId=get_trace_id()
    )

def success_data(data: T, msg: str = "ok") -> AjaxJson[T]:
    return AjaxJson[T](
        code=CODE_SUCCESS,
        msg=msg,
        data=data,
        traceId=get_trace_id()
    )

def success_page(data: T, data_count: int) -> AjaxJson[T]:
    return AjaxJson(
        code=CODE_SUCCESS,
        msg="ok",
        data=data,
        dataCount=data_count,
        traceId=get_trace_id()
    )

def error(code: str, msg: str, data: Any = None) ->AjaxJson:
    return AjaxJson(
        code=code,
        msg=msg,
        data=data,
        traceId=get_trace_id()
    )