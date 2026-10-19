"""存储源参数模型，对应 Java module/storage/model/param/ 包。

分工：

    params.py   从 DB / 前端表单读入的输入，一个存储源实例一份
    schemas.py  发给前端的输出（FileItemResult、StorageSourceMetadata）

字段名保持 Java 原名（camelCase）：它们同时是 storage_source_config.name、
前端动态表单的 key 和 URL 查询参数名，改成 snake_case 会同时破坏三处契约。

Java 的 @StorageParamItem 注解（name / order / description / condition /
defaultValue）在这里退化为字段与默认值。其余元数据用于后台管理界面的表单渲染，
后续做存储源管理时可考虑用 Pydantic 的 Field(json_schema_extra=...) 表达。
"""

from pydantic import BaseModel


class ProxyTransferParam(BaseModel):
    """对应 ProxyTransferParam.java。默认值来自 Java 注解的 defaultValue 属性。"""

    # 加速域名：配置后用于拼下载直链，未配置则走服务器中转（/pd/）
    domain: str | None = None
    # 生成签名链接（私有空间），默认开启
    proxyPrivate: bool = True
    # 下载签名有效期，单位秒
    proxyTokenTime: int | None = 1800
    # 下载时强制 Content-Disposition: attachment
    proxyLinkForceDownload: bool = True


class LocalParam(ProxyTransferParam):
    """对应 LocalParam.java：本地存储只有 filePath 一个自有参数。

    filePath 是宿主机上的真实绝对路径，Docker 部署时需要提前映射卷。
    """

    filePath: str
