"""token 签发/校验 + 当前用户依赖。

对应 Java 的 Sa-Token（StpUtil）+ ZFileAuthUtil。三个语义必须对上：

  1. token 从 `zfile-token` 请求头取（= sa-token.token-name 配置）
  2. "未登录"不是错误：get_current_user_id 永不失败，兜底成匿名用户 id=2
  3. "真的没登录"（checkLogin 要判断）和"拿到一个用户"是两件事，所以拆成
     get_login_id / get_current_user_id 两层 —— 对应 StpUtil.isLogin() 与 getLoginId(默认值)

下面三个存储函数就是 Sa-Token 的 SaTokenDao 的最小版：v1 用内存 dict，
进程重启 = 所有登录失效（前端表现为变回未登录，属预期）。
以后换 SQLite/Redis 只改这三个函数体。
"""

import secrets

from fastapi import Depends, Header
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.user import ANONYMOUS_ID, User

_tokens: dict[str, int] = {}


def save_token(token: str, user_id: int) -> None:
    # 写入user_id作为token
    _tokens[token] = user_id

def read_token(token: str) -> int | None:
    # 读不到就返回none
    return _tokens.get(token)


def delete_token(token: str) -> None:
    # 删除, 不存在的情况下返回none
    _tokens.pop(token,None)


def issue_token(user_id: int) -> str:
    # secrets.token_urlsafe(32) 生成 → save_token 落库 → 返回 token。
    token = secrets.token_urlsafe(32)
    save_token(token, user_id)
    return token


def get_token(x_zfile_token: str | None = Header(default=None, alias="zfile-token")) -> str | None:
    """从请求头取 token。匿名访问时是 None。"""
    return x_zfile_token


def get_login_id(token: str | None = Depends(get_token)) -> int | None:
    # 有 token 就 read_token，否则 None。checkLogin 只认这一层。
    # 不直接与前端对接 使用下一个代理函数调用这个数据访问接口 做访问降级
    return read_token(token) if token else None


def get_current_user_id(login_id: int | None = Depends(get_login_id)) -> int:
    """不能报错，未登录兜底成 ANONYMOUS_ID。
    "取不到登录态"在这里被翻译成"你是匿名用户 2"
    """
    return login_id if login_id is not None else ANONYMOUS_ID
    # raise NotImplementedError


def get_current_user(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> User | None:
    # 从数据库查询user_id
    return db.get(User,user_id)
