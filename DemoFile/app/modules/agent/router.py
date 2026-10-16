"""agent 会话路由（Phase A）：HTTP 控制面 + SSE 事件流。

    POST   /api/agent/session              新建会话（当前登录用户）
    GET    /api/agent/sessions             列出自己的会话
    GET    /api/agent/{agent_id}           会话状态
    POST   /api/agent/{agent_id}/message   发送消息（异步；回答与工具轨迹走 SSE）
    POST   /api/agent/{agent_id}/cancel    中止当前轮次
    DELETE /api/agent/{agent_id}           关闭会话
    GET    /api/agent/{agent_id}/events    SSE 事件流（?since=N 断线重放）

设计要点：
- 全部要求登录（匿名 → 401 信封）。会话归属校验在 AgentHost，他人会话一律回
  BIZ_NOT_FOUND，不泄露存在性。
- message 立即返回：agent loop 是常驻任务，HTTP 只往 inbox 投递（followup），
  不阻塞等待回答 —— 前端消费 SSE 拿跟读。
- SSE 鉴权：请求头 zfile-token 优先；浏览器 EventSource 无法带自定义头，
  支持 ?token= 兜底（内网个人站，接受 URL 带 token 的取舍）。
- SSE 开流前的错误（未登录/会话不存在）直接抛 → 全局处理器回 JSON 信封，
  前端按 content-type 区分信封与流。
- 路由注册顺序：/session、/sessions 必须在 /{agent_id} 之前（否则被路径参数吞掉）。
"""

import logging

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from app.agent.host import agent_host
from app.core.auth import get_login_id, get_token, read_token
from app.core.errors import UnauthorizedAccessException
from app.core.response import AjaxJson, success, success_data
from mini_harness.agent import Agent
from app.modules.agent.schemas import AgentMessageRequest, AgentStatusResult

log = logging.getLogger(__name__)

router = APIRouter(prefix="/agent", tags=["agent"])


def _require_login(login_id: int | None) -> int:
    if login_id is None:
        raise UnauthorizedAccessException()
    return login_id


def _to_result(agent: Agent) -> AgentStatusResult:
    last_error = agent.last_error
    return AgentStatusResult(
        id=agent.id,
        status=agent.status,
        lastError=f"{type(last_error).__name__}: {last_error}" if last_error is not None else None,
    )


@router.post("/session")
async def create_session(
    login_id: int | None = Depends(get_login_id),
) -> AjaxJson[AgentStatusResult]:
    user_id = _require_login(login_id)
    agent = agent_host.create(user_id)
    return success_data(_to_result(agent), "会话已创建")


@router.get("/sessions")
async def list_sessions(
    login_id: int | None = Depends(get_login_id),
) -> AjaxJson[list[AgentStatusResult]]:
    user_id = _require_login(login_id)
    return success_data([_to_result(agent) for agent in agent_host.list_owned(user_id)])


@router.get("/{agent_id}")
async def session_status(
    agent_id: str,
    login_id: int | None = Depends(get_login_id),
) -> AjaxJson[AgentStatusResult]:
    user_id = _require_login(login_id)
    return success_data(_to_result(agent_host.get_owned(agent_id, user_id)))


@router.post("/{agent_id}/message")
async def send_message(
    agent_id: str,
    request: AgentMessageRequest,
    login_id: int | None = Depends(get_login_id),
) -> AjaxJson:
    user_id = _require_login(login_id)
    agent = agent_host.get_owned(agent_id, user_id)
    agent.followup(request.content)
    return success("已接收")


@router.post("/{agent_id}/cancel")
async def cancel_turn(
    agent_id: str,
    login_id: int | None = Depends(get_login_id),
) -> AjaxJson:
    user_id = _require_login(login_id)
    agent = agent_host.get_owned(agent_id, user_id)
    agent.cancel()
    return success("已中止")


@router.delete("/{agent_id}")
async def close_session(
    agent_id: str,
    login_id: int | None = Depends(get_login_id),
) -> AjaxJson:
    user_id = _require_login(login_id)
    await agent_host.dispose(agent_id, user_id)
    return success("会话已关闭")


@router.get("/{agent_id}/events")
async def session_events(
    agent_id: str,
    since: int = Query(
        default=-1,
        ge=-1,
        description="已收到的最后 seq，重放其后事件；-1（默认）从头重放",
    ),
    token: str | None = Query(default=None, description="EventSource 无法带头时的兜底"),
    header_token: str | None = Depends(get_token),
) -> StreamingResponse:
    login_id = read_token(header_token) if header_token else None
    if login_id is None and token:
        login_id = read_token(token)
    user_id = _require_login(login_id)
    agent_host.get_owned(agent_id, user_id)  # 开流前校验，错误走 JSON 信封
    return StreamingResponse(
        agent_host.stream(agent_id, user_id, since),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
