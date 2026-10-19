"""用户模块的请求/响应模型。字段名 = JSON key，逐个对照 Java 的 model/request|result。"""

from pydantic import BaseModel, Field


class UserLoginRequest(BaseModel):
    """对应 UserLoginRequest.java。

    Java 侧 username/password 标注了 @NotBlank；空值由校验处理器转为 HTTP 400 +
    code 41000 + 字段 map。verifyCode 两个字段选填。
    """

    username: str = Field(min_length=1)
    password: str = Field(min_length=1)
    verifyCode: str | None = None
    verifyCodeUUID: str | None = None


class LoginResult(BaseModel):
    """对应 LoginResult.java。字段名就是 token / admin（不是 isAdmin）。"""

    token: str
    admin: bool


class CheckLoginResult(BaseModel):
    """对应 CheckLoginResult.java。字段名自带 is 前缀，与 Java 保持一致。"""

    isLogin: bool
    isAdmin: bool | None = None
    username: str | None = None
    nickname: str | None = None


class LoginVerifyImgResult(BaseModel):
    """对应 LoginVerifyImgResult.java。当前为空实现，避免登录失败路径因 404 受干扰。"""

    imgBase64: str = ""
    uuid: str = ""
