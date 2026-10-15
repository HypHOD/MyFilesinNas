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

    用途：前端 useFileData.loadFile() 每个"打开目录"动作都发它 —— 点存储源、
    进文件夹、点面包屑、点表头排序，全走这一条（useFileData.js:89-97 组装这 5 个字段）。
    """

    storageKey: str
    path: str | None = None
    password: str | None = None
    # Java 侧 @StringListValue 校验合法值；Pydantic 用 Literal 达成同样效果 ——
    # 非法值直接走 RequestValidationError → 41000，不用手写校验代码。
    orderBy: Literal["name", "size", "time"] | None = None
    orderDirection: Literal["asc", "desc"] | None = None

    def handle_default_value(self) -> None:
        """对应 handleDefaultValue()。router 拿到请求后第一件事就调它。

        用途：补默认值 + 规范化 path —— 之后整条链和 service 可以假定
        path 一定以 '/' 开头、orderBy/orderDirection 一定有值，排序命令不用各自判空。

        规格（照 Java FileListRequest.java:36-49）：
          - path 为空 → "/"；orderBy 为空 → "name"；orderDirection 为空 → "asc"
          - 最后 self.path = concat(self.path)（app/core/path_utils 的 concat）：
            补前导 '/'、合并重复 '/' —— "a" → "/a"、"//a//b" → "/a/b"

        TODO 写实现
        """
        # raise NotImplementedError
        if not self.path:
            self.path="/"
        if not self.orderBy:
            self.orderBy="name"
        if not self.orderDirection:
            self.orderDirection = "asc"
        self.path = concat(self.path)
