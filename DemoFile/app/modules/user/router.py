"""登录相关接口。对应 UserController.java。

路径和参数名以前端 src/api/home/user.js 为准，别从 Controller 猜。
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

    TODO：
      1. get_by_username 找不到 → BizException(ErrorCode.BIZ_LOGIN_ERROR)
      2. verify_password 不过  → 同样抛 BIZ_LOGIN_ERROR（不区分"用户不存在"和"密码错"）
      3. issue_token(user.id)
      4. data = LoginResult(token=..., admin=is_admin(user.id))
         注意 msg 是 "登录成功"，不是 success_data() 里写死的 "ok"

    以后要支持自定义登录入口时，再加一条 @router.post("/login/{entry}")，
    handler 里跟 system_config.secureLoginEntry 比对一次即可（Java 是运行时注册路由，
    见 DynamicLoginEntryService —— FastAPI 不需要那么绕）。
    """
    user = get_by_username(db,request.username)
    if user is None or not verify_password(user.password,user.salt,request.password):
        raise BizException(ErrorCode.BIZ_LOGIN_ERROR)

    result = LoginResult(token=issue_token(user.id),admin=is_admin(user.id))
    return success_data(result,"登录成功")
    # raise NotImplementedError


@router.post("/logout")
def logout(token: str | None = Depends(get_token)) -> AjaxJson:
    """对应 UserController.logout()。

    TODO：delete_token(token)，然后返回 success("注销成功")。
    没有 token 时也必须成功 —— 匿名调 log 出是合法请求。
    """
    if token:
        delete_token(token)
    return success("注销成功")
    # raise NotImplementedError


@router.get("/login/check")
def check_login(
    user: User | None = Depends(get_current_user),
    login_id: int | None = Depends(get_login_id),
) -> AjaxJson[CheckLoginResult]:
    """对应 UserController.checkLogin()。

    ⚠️ 匿名必须返回 code "0" + {isLogin: false}。
    Header.vue:341 每次挂载都无条件调它，返回 42000 会把每个访客都踢去登录页。

    TODO：
      isLogin 取 login_id is not None（**不是** user.id != 2 —— 语义不同）
      已登录时再填 isAdmin / username / nickname
    """
    result = CheckLoginResult(isLogin=login_id is not None)
    if login_id is not None and user is not None:
        result.isAdmin = is_admin(user.id)
        result.username = user.username
        result.nickname = user.nickname
    return success_data(result)
    # raise NotImplementedError


@router.get("/login/verify-mode")
def login_verify_mode(username: str = Query(default="")) -> AjaxJson[str]:
    """对应 UserController.loginVerifyMode()。

    v1 恒返回 "off" —— 这正是 Java 在 loginImgVerify=false、adminTwoFactorVerify=false、
    loginVerifySecret 为空时的默认行为（seed 里就是这个值）。
    """
    return success_data("off")


@router.get("/login/entry/validate")
def validate_login_entry(
    entry: str = Query(default=""),
    db: Session = Depends(get_db),
) -> AjaxJson:
    """对应 UserController.validateLoginEntry()。

    ⚠️ 这个接口必须实现：login.vue:125-134 在 onMounted 里先校验，失败就 router.replace("/")。
    不实现的话（404 → 前端 catch）登录页永远进不去。

    TODO：读 system_config.secureLoginEntry：
      为 None → 放行
      否则和 entry 精确相等才放行，不等时**返回**（不是抛）
      error("50000", "安全登录入口不正确") —— 注意是 HTTP 200 + 非 0 code
    """
    secure_entry = get_site_config(db).secureLoginEntry
    if secure_entry is None or secure_entry ==entry:
        return success()
    return error(ErrorCode.SYSTEM_ERROR.code,"安全登录入口不正确")
    # raise NotImplementedError


@router.get("/login/captcha")
def captcha() -> AjaxJson[LoginVerifyImgResult]:
    """对应 UserController.captcha()。

    v1 stub：verify-mode 恒 off 时前端正常不会调，但 login.vue:186 的失败分支会无条件调它，
    给个空结果省得调试登录问题时被 404 干扰。
    """
    return success_data(LoginVerifyImgResult())
