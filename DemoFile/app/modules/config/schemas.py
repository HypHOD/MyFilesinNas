"""系统配置的两层模型。

对应 Java 的两个包：
  SystemConfigDTO          module/config/model/dto/SystemConfigDTO.java        (内部)
  FrontSiteConfigResult    module/config/model/result/FrontSiteConfigResult.java (对外)

两个类必须保持分离：SiteConfig 包含 username/password，FrontSiteConfigResult
面向匿名访客；合并会导致管理员密码明文泄露。
"""

from typing import Any

from pydantic import BaseModel


class SiteConfig(BaseModel):
    """内部模型。字段名与 system_config.name、JSON key 保持一致。

    这 47 个字段对应 FrontSiteConfigResult 中从数据库取值的部分，另补充了几个
    仅内部使用的字段；后续按需增加。
    """

    # —— FrontSiteConfigResult 中来自 DB 的 47 个 ——
    installed: bool | None = None
    directLinkPrefix: str | None = None
    siteName: str | None = None
    icp: str | None = None
    layout: str | None = None
    mobileLayout: str | None = None
    mobileShowSize: bool | None = None
    tableSize: str | None = None
    showLinkBtn: bool | None = None
    showShortLink: bool | None = None
    showPathLink: bool | None = None
    showDocument: bool | None = None
    showAnnouncement: bool | None = None
    announcement: str | None = None
    customJs: str | None = None
    customCss: str | None = None
    customVideoSuffix: str | None = None
    customImageSuffix: str | None = None
    customAudioSuffix: str | None = None
    customTextSuffix: str | None = None
    customOfficeSuffix: str | None = None
    customKkFileViewSuffix: str | None = None
    rootShowStorage: bool | None = None
    forceBackendAddress: str | None = None
    frontDomain: str | None = None
    showLogin: bool | None = None
    loginLogMode: str | None = None
    fileClickMode: str | None = None
    mobileFileClickMode: str | None = None
    maxFileUploads: int | None = None
    onlyOfficeUrl: str | None = None
    kkFileViewUrl: str | None = None
    kkFileViewOpenMode: str | None = None
    maxShowSize: int | None = None
    loadMoreSize: int | None = None
    defaultSortField: str | None = None
    defaultSortOrder: str | None = None
    siteHomeName: str | None = None
    siteHomeLogo: str | None = None
    siteHomeLogoLink: str | None = None
    siteHomeLogoTargetMode: str | None = None
    # DB 中为 JSON 字符串（Java 通过 @JSONStringParse 解析）。当前原样返回；
    # 实现短链功能时再增加 field_validator 解析。
    linkExpireTimes: str | None = None
    defaultSavePwd: bool | None = None
    enableNormalDownloadConfirm: bool | None = None
    enablePackageDownloadConfirm: bool | None = None
    enableBatchDownloadConfirm: bool | None = None
    enableHoverMenu: bool | None = None

    # —— 只有内部用，不进响应 ——
    username: str | None = None
    password: str | None = None
    guestIndexHtml: str | None = None
    secureLoginEntry: str | None = None
    # AES 下载签名密钥（HEX）。绝不能进入 FrontSiteConfigResult：泄漏后可伪造任意下载链接。
    rsaHexKey: str | None = None

    @classmethod
    def from_rows(cls, rows: dict[str, str | None]) -> "SiteConfig":
        """把 system_config 的 {name: value} 灌成模型。

        对应 Java SystemConfigService.getSystemConfig() 中的反射逻辑。
        Pydantic 宽松模式会完成 "true" → True、"5" → 5 的转换，等价于 Java 的
        Convert.convert(field.getType(), strVal)。
        """
        return cls.model_validate(rows)


class FrontSiteConfigResult(BaseModel):
    """响应契约。漏字段不会报错，但会导致前端行为静默错误。"""

    # —— 来自 system_config ——
    installed: bool | None = None
    directLinkPrefix: str | None = None
    siteName: str | None = None
    icp: str | None = None
    layout: str | None = None
    mobileLayout: str | None = None
    mobileShowSize: bool | None = None
    tableSize: str | None = None
    showLinkBtn: bool | None = None
    showShortLink: bool | None = None
    showPathLink: bool | None = None
    showDocument: bool | None = None
    showAnnouncement: bool | None = None
    announcement: str | None = None
    customJs: str | None = None
    customCss: str | None = None
    customVideoSuffix: str | None = None
    customImageSuffix: str | None = None
    customAudioSuffix: str | None = None
    customTextSuffix: str | None = None
    customOfficeSuffix: str | None = None
    customKkFileViewSuffix: str | None = None
    rootShowStorage: bool | None = None
    forceBackendAddress: str | None = None
    frontDomain: str | None = None
    showLogin: bool | None = None
    loginLogMode: str | None = None
    fileClickMode: str | None = None
    mobileFileClickMode: str | None = None
    maxFileUploads: int | None = None
    onlyOfficeUrl: str | None = None
    kkFileViewUrl: str | None = None
    kkFileViewOpenMode: str | None = None
    maxShowSize: int | None = None
    loadMoreSize: int | None = None
    defaultSortField: str | None = None
    defaultSortOrder: str | None = None
    siteHomeName: str | None = None
    siteHomeLogo: str | None = None
    siteHomeLogoLink: str | None = None
    siteHomeLogoTargetMode: str | None = None
    linkExpireTimes: Any = None
    defaultSavePwd: bool | None = None
    enableNormalDownloadConfirm: bool | None = None
    enablePackageDownloadConfirm: bool | None = None
    enableBatchDownloadConfirm: bool | None = None
    enableHoverMenu: bool | None = None

    # —— 算出来的，不来自 system_config ——
    debugMode: bool = False  # Java 从配置文件读取，这里固定为 False
    guest: bool = False  # 匿名访客标记，由路由层计算后填充


class FileListConfigRequest(BaseModel):
    """对应 FileListConfigRequest.java：POST /api/site/config/storage 的请求体。

    前端 useFileData.js 传的就是这三个字段（storageKey 必填，path 默认 "/"）。
    """

    storageKey: str
    path: str = "/"
    password: str | None = None
