from sqlalchemy.orm import Session

from app.core.errors import BizException, ErrorCode
from app.modules.config.schemas import SiteConfig
from app.modules.config.service import get_site_config, update_site_config
from app.modules.install.schemas import InstallSystemRequest

from app.models.user import ADMIN_ID, User
from app.modules.user.service import encrypt_password


def get_system_is_installed(db: Session) -> bool:
    """对应 InstallService.getSystemIsInstalled()。

    以 system_config.installed 为准，而不是管理员用户名；Swagger 上的描述不可靠。
    """
    return bool(get_site_config(db).installed)


def install(db: Session, request: InstallSystemRequest) -> None:
    """对应 InstallService.install()。

    只向 system_config 写入 siteName 和 installed 两个字段，依赖部分更新语义。
    管理员密码按现有规则加盐哈希后保存。
    """

    if get_system_is_installed(db):
        raise BizException(ErrorCode.BIZ_SYSTEM_ALREADY_INIT)

    admin = db.get(User, ADMIN_ID)
    if admin is None:
        # Java 这句是硬编码字符串，没走 ErrorCode 表
        raise BizException(ErrorCode.SYSTEM_ERROR,
                           "系统异常，管理员用户不存在，请检测数据库或重建数据库。")

    admin.username = request.username
    admin.password, admin.salt = encrypt_password(request.password)
    # update_site_config 内部的 commit 会一并提交 admin 的改动
    update_site_config(db, SiteConfig(siteName=request.siteName, installed=True))
