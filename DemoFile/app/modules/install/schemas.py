from pydantic import BaseModel


class InstallSystemRequest(BaseModel):
    """对应 InstallSystemRequest.java。

    三个字段均为选填：Java 侧 method 签名上没有 @Valid，这里保持一致。
    """

    siteName: str | None = None
    username: str | None = None
    password: str | None = None
