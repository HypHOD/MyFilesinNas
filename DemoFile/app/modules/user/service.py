"""用户与密码。对应 Java 的 UserService + PasswordVerifyUtils。

密码哈希公式已用 hutool 5.8.31 探针对拍验证（含中文密码），保持一致。
token 与 HTTP 逻辑不在此模块，分别在 app/core/auth.py 和 router.py。
"""

import hashlib
import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user import ADMIN_ID, User


def md5(value: str) -> str:
    return hashlib.md5(value.encode()).hexdigest()


def sha1(value: str) -> str:
    return hashlib.sha1(value.encode()).hexdigest()


def verify_password(db_password: str | None, db_salt: str | None, raw: str) -> bool:
    """对应 PasswordVerifyUtils.verify()。

    无 salt → md5(明文)，兼容加盐之前的旧数据；
    有 salt → md5(sha1(明文) + salt)，先 hexdigest 再拼字符串，不是字节拼接。
    """
    if not db_salt:
        return db_password == md5(raw)
    return db_password == md5(sha1(raw) + db_salt)


def encrypt_password(raw: str) -> tuple[str, str]:
    """对应 PasswordVerifyUtils.encrypt()，返回 (hash, salt)，安装时使用。

    salt = md5(sha1(当前毫秒时间戳的十进制字符串))，再计算
    md5(sha1(明文) + salt)。
    """
    salt = md5(sha1(str(int(time.time()*1000))))
    return md5(sha1(raw) + salt), salt


def get_by_username(db: Session, username: str) -> User | None:
    """对应 UserService.getByUsername()。"""
    return db.scalar(select(User).where(User.username == username))


def is_admin(user_id: int) -> bool:
    """对应 UserService.isAdmin(Integer)。管理员 ID 固定为 1，没有角色表。"""
    return user_id == ADMIN_ID
