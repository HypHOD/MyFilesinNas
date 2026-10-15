"""用户与密码。对应 Java 的 UserService + PasswordVerifyUtils。

公式已在步骤 0 用 hutool 5.8.31 探针对拍验证过（含中文密码），照抄即可。
其余逻辑（token、HTTP）不在这里 —— 分别在 app/core/auth.py 和 router.py。
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

    TODO 两个分支：
      无 salt → md5(明文)                  —— 兼容加盐之前的旧数据，别漏这个分支
      有 salt → md5(sha1(明文) + salt)     —— 先 hexdigest() 再拼字符串，不是 bytes 相加
    """
    if not db_salt:
        return db_password == md5(raw)
    return db_password == md5(sha1(raw) + db_salt)
    # raise NotImplementedError


def encrypt_password(raw: str) -> tuple[str, str]:
    """对应 PasswordVerifyUtils.encrypt()，返回 (hash, salt)。安装时用。

    TODO：salt = md5(sha1(str(当前毫秒时间戳)))，再算 md5(sha1(明文) + salt)。
    注意时间戳要转成十进制字符串（Java 的 String.valueOf(long)）。
    """
    salt = md5(sha1(str(int(time.time()*1000))))
    return md5(sha1(raw) + salt), salt
    # raise NotImplementedError


def get_by_username(db: Session, username: str) -> User | None:
    """对应 UserService.getByUsername()。

    TODO：db.scalar(select(User).where(User.username == username))
    """
    return db.scalar(select(User).where(User.username == username))
    # raise NotImplementedError


def is_admin(user_id: int) -> bool:
    """对应 UserService.isAdmin(Integer)。管理员 ID 强制为 1，没有角色表。"""
    return user_id == ADMIN_ID
    # raise NotImplementedError
