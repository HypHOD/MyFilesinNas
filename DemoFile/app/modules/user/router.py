"""登录相关接口。对应 UserController.java。

路径与参数名以前端 src/api/home/user.js 为准，不要从 Controller 推断。
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.auth import (
    delete_token,
    get_current_user,
    get_login_id,
    get_token,
    issue_token,
)
from app.core.db import get_db
from app.core.errors import BizException, ErrorCode
from app.core.response import CODE_SUCCESS, AjaxJson, error, success, success_data
from app.models.user import User
from app.modules.user.schemas import (
    CheckLoginResult,
    LoginResult,
    LoginVerifyImgResult,
    UserLoginRequest,
)
from app.modules.user.service import get_by_username, is_admin, verify_password
from app.modules.config.service import get_site_config

router = APIRouter(prefix="/user", tags=["user"])


@router.post("/login")
def do_login(request: UserLoginRequest, db: Session = Depends(get_db)) -> AjaxJson[LoginResult]:
    """对应 UserController.doLogin()。

    用户不存在与密码错误统一抛 BIZ_LOGIN_ERROR，不区分两者。
    鉴权通过后签发 token，返回 LoginResult(token, admin)；msg 为 "登录成功"，
    而不是 success_data() 默认的 "ok"。

    支持自定义登录入口时增加 @router.post("/login/{entry}")，在 handler 中与
    system_config.secureLoginEntry 比对即可（Java 通过 DynamicLoginEntryService
    运行时注册路由，FastAPI 无需如此）。
    """
    user = get_by_username(db,request.username)
    if user is None or not verify_password(user.password,user.salt,request.password):
        raise BizException(ErrorCode.BIZ_LOGIN_ERROR)

    result = LoginResult(token=issue_token(user.id),admin=is_admin(user.id))
    return success_data(result,"登录成功")


@router.post("/logout")
def logout(token: str | None = Depends(get_token)) -> AjaxJson:
    """对应 UserController.logout()。

    删除 token 后返回 success("注销成功")。没有 token 时同样必须成功：匿名调用
    logout 是合法请求。
    """
    if token:
        delete_token(token)
    return success("注销成功")


@router.get("/login/check")
def check_login(
    user: User | None = Depends(get_current_user),
    login_id: int | None = Depends(get_login_id),
) -> AjaxJson[CheckLoginResult]:
    """对应 UserController.checkLogin()。

    匿名请求必须返回 code "0" + {isLogin: false}。Header.vue:341 每次挂载都会无条件
    调用该接口，返回 42000 会把所有访客重定向到登录页。

    isLogin 取 login_id is not None（而不是 user.id != 2，两者语义不同）。
    已登录时补充 isAdmin / username / nickname。
    """
    result = CheckLoginResult(isLogin=login_id is not None)
    if login_id is not None and user is not None:
        result.isAdmin = is_admin(user.id)
        result.username = user.username
        result.nickname = user.nickname
    return success_data(result)


@router.get("/login/verify-mode")
def login_verify_mode(username: str = Query(default="")) -> AjaxJson[str]:
    """对应 UserController.loginVerifyMode()。

    固定返回 "off"，对应 Java 在 loginImgVerify=false、adminTwoFactorVerify=false、
    loginVerifySecret 为空时的默认行为（seed 中即为该值）。
    """
    return success_data("off")


@router.get("/login/entry/validate")
def validate_login_entry(
    entry: str = Query(default=""),
    db: Session = Depends(get_db),
) -> AjaxJson:
    """对应 UserController.validateLoginEntry()。

    该接口必须实现：login.vue:125-134 在 onMounted 中先校验，失败会
    router.replace("/")；未实现（404 → 前端 catch）会导致登录页无法进入。

    读取 system_config.secureLoginEntry：为 None 时放行；否则要求 entry 精确相等，
    不等时返回 error("50000", "安全登录入口不正确")（HTTP 200 + 非 0 code），
    而不是抛异常。
    """
    secure_entry = get_site_config(db).secureLoginEntry
    if secure_entry is None or secure_entry ==entry:
        return success()
    return error(ErrorCode.SYSTEM_ERROR.code,"安全登录入口不正确")


@router.get("/login/captcha")
def captcha() -> AjaxJson[LoginVerifyImgResult]:
    """对应 UserController.captcha()。

    当前为空实现：verify-mode 恒为 off 时前端通常不会调用，但 login.vue:186 的
    失败分支会无条件调用；返回空结果，避免调试登录问题时被 404 干扰。
    """
    return success_data(LoginVerifyImgResult())
