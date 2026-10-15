from pydantic import BaseModel


class InstallSystemRequest(BaseModel):
    """照抄 InstallSystemRequest.java。

    Java 侧 method 签名上没有 @Valid，所以这三个字段都没有校验 —— 我们也保持一致。
    """

    siteName: str | None = None
    username: str | None = None
    password: str | None = None
