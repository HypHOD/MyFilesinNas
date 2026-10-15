"""存储源参数模型。对应 Java module/storage/model/param/ 包。

和 schemas.py 的分工：

    params.py   ← 从 DB / 前端表单来的**输入**（一个存储源实例一份）
    schemas.py  ← 发给前端的**输出**（FileItemResult、StorageSourceMetadata）

⚠️ 字段名保持 Java 原名（camelCase）：它们同时是 storage_source_config.name、
前端动态表单的 key、URL 查询参数名，三位一体，改成 snake_case 就对不上了。

Java 那套 @StorageParamItem 注解（name / order / description / condition / defaultValue）
在这里退化成"字段 + 默认值"两件事 —— 注解剩下的元数据（表单标签、排序、显示条件）
是**给后台管理界面用的**，等步骤 5 做存储源管理时再想怎么表达（提示：Pydantic 的
Field(json_schema_extra=...) 和 model_json_schema() 基本是免费的）。
"""

from pydantic import BaseModel


class ProxyTransferParam(BaseModel):
    """对应 ProxyTransferParam.java。默认值来自 Java 注解的 defaultValue 属性。"""

    # 加速域名：填了就用它拼下载直链，不填走服务器中转（/pd/）
    domain: str | None = None
    # 生成签名链接（私有空间）。注意默认是 **true**
    proxyPrivate: bool = True
    # 下载签名有效期，单位秒。Java 注解默认 "1800"
    proxyTokenTime: int | None = 1800
    # 下载链接强制下载（Content-Disposition: attachment）
    proxyLinkForceDownload: bool = True


class LocalParam(ProxyTransferParam):
    """对应 LocalParam.java：本地存储只有 filePath 一个自有参数。

    filePath = 宿主机上的真实绝对路径（Docker 部署要提前映射卷）。
    """

    filePath: str
