from pydantic import BaseModel, Field


class ResponseModel(BaseModel):
    """内部操作结果，经 u_response 转换为 HTTP 响应。"""

    status: bool = Field(..., json_schema_extra={"example": True})
    status_code: int = Field(..., json_schema_extra={"example": 200})
    msg_en: str
    msg_zh: str
    data: dict | None = None


class APIResponse(BaseModel):
    """API 路由的文档响应模型（实际内容为 msg_en/msg_zh）。"""

    status: bool = Field(..., json_schema_extra={"example": True})
    msg_en: str = Field(..., json_schema_extra={"example": "Success"})
    msg_zh: str = Field(..., json_schema_extra={"example": "成功"})
