from sqlalchemy.orm import Session

from app.core.errors import BizException, ErrorCode
from app.modules.config.schemas import SiteConfig
from app.modules.config.service import get_site_config, update_site_config
from app.modules.install.schemas import InstallSystemRequest

from app.models.user import ADMIN_ID, User
from app.modules.user.service import encrypt_password


def get_system_is_installed(db: Session) -> bool:
    """对应 InstallService.getSystemIsInstalled()。

    ⚠️ Swagger 上写的描述是"根据管理员用户名是否存在判断"，**是错的**。
    代码读的是 system_config.installed。以代码为准。
    """
    return bool(get_site_config(db).installed)


def install(db: Session, request: InstallSystemRequest) -> None:
    """对应 InstallService.install()。

    只往 system_config 写 siteName + installed 两个字段 —— 正是"部分更新"语义要保证的东西。
    管理员密码暂时存明文，步骤 3 换成 md5(sha1(密码) + salt)。
    """

    if get_system_is_installed(db):
        raise BizException(ErrorCode.BIZ_SYSTEM_ALREADY_INIT)

    admin = db.get(User, ADMIN_ID)
    if admin is None:
        # Java 这句是硬编码字符串，没走 ErrorCode 表
        raise BizException(ErrorCode.SYSTEM_ERROR,
                           "系统异常，管理员用户不存在，请检测数据库或重建数据库。")

    admin.username = request.username
    # TODO 步骤 3：改成 admin.password, admin.salt = encrypt_password(request.password)
    # 现在是明文 —— 装完的系统登录必然失败（verify 会走无 salt 分支去比 md5）
    admin.password, admin.salt = encrypt_password(request.password)
    # 不用再 db.commit()：update_site_config 内部的提交会把 admin 的改动一起带上
    update_site_config(db, SiteConfig(siteName=request.siteName, installed=True))
