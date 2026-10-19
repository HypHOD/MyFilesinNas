"""token 签发/校验与当前用户依赖。

语义对齐 Java 的 Sa-Token（StpUtil）+ ZFileAuthUtil：

- token 从 ``zfile-token`` 请求头读取（= sa-token.token-name 配置）；
- 未登录不是错误：get_current_user_id 不失败，兜底为匿名用户 id=2；
- "是否登录"与"拿到一个用户"是两件事，拆成 get_login_id / get_current_user_id
  两层，对应 StpUtil.isLogin() 与 getLoginId(默认值)。

token 存储是 Sa-Token SaTokenDao 的最小实现：内存 dict，进程重启后登录态全部失效
（前端表现为回到未登录，属预期）。替换为 SQLite/Redis 只需改这三个函数体。
"""

import secrets

from fastapi import Depends, Header
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.user import ANONYMOUS_ID, User

_tokens: dict[str, int] = {}


def save_token(token: str, user_id: int) -> None:
    _tokens[token] = user_id


def read_token(token: str) -> int | None:
    return _tokens.get(token)


def delete_token(token: str) -> None:
    _tokens.pop(token, None)


def issue_token(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    save_token(token, user_id)
    return token


def get_token(x_zfile_token: str | None = Header(default=None, alias="zfile-token")) -> str | None:
    """从请求头取 token。匿名访问时是 None。"""
    return x_zfile_token


def get_login_id(token: str | None = Depends(get_token)) -> int | None:
    # checkLogin 只认这一层；路由层通过 get_current_user_id 做匿名降级。
    return read_token(token) if token else None


def get_current_user_id(login_id: int | None = Depends(get_login_id)) -> int:
    """不抛错；未登录时返回 ANONYMOUS_ID。"""
    return login_id if login_id is not None else ANONYMOUS_ID


def get_current_user(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> User | None:
    return db.get(User, user_id)
