"""agent 会话的请求/响应模型（字段 camelCase = 前端契约）。"""

from pydantic import BaseModel


class AgentMessageRequest(BaseModel):
    content: str


class AgentStatusResult(BaseModel):
    id: str
    status: str  # idle / running
    lastError: str | None = None
