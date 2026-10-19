"""module/storage 的 HTTP 请求模型。对应 Java module/storage/model/request/base/。

响应模型不在这 —— FileInfoResult / FileItemResult 在 app/storage/schemas.py
（那边是"存储层对外输出的模型"，两个包在 Java 侧同属 model/ 下属子包）。
请求模型留在模块层：它是 HTTP 契约、由 router 声明，存储层内部只消费。
"""

from typing import Literal

from pydantic import BaseModel

from app.core.path_utils import concat


class FileListRequest(BaseModel):
    """对应 FileListRequest.java：POST /api/storage/files 的请求体。

    前端每次打开目录、点击面包屑或表头排序都会发送该请求，包含这 5 个字段。
    """

    storageKey: str
    path: str | None = None
    password: str | None = None
    # Java 侧 @StringListValue 校验合法值；Pydantic 用 Literal 达成同样效果 ——
    # 非法值直接走 RequestValidationError → 41000，不用手写校验代码。
    orderBy: Literal["name", "size", "time"] | None = None
    orderDirection: Literal["asc", "desc"] | None = None

    def handle_default_value(self) -> None:
        """对应 handleDefaultValue()，router 收到请求后首先调用。

        补默认值并规范化 path，之后整条链可以假定 path 以 '/' 开头、排序参数有值。
        path 为空时改为 "/"，orderBy 默认 "name"，orderDirection 默认 "asc"；
        concat 负责补前导斜杠并合并重复斜杠。
        """
        if not self.path:
            self.path="/"
        if not self.orderBy:
            self.orderBy="name"
        if not self.orderDirection:
            self.orderDirection = "asc"
        self.path = concat(self.path)
