"""系统配置的两层模型。

Java 把它们放在两个包：
  SystemConfigDTO          -> module/config/model/dto/SystemConfigDTO.java        (内部)
  FrontSiteConfigResult    -> module/config/model/result/FrontSiteConfigResult.java (对外)

放一个文件里方便对照，但**两个类必须分开**：SiteConfig 里有 username/password，
FrontSiteConfigResult 是发给匿名访客的，两者混在一起就是明文泄露管理员密码。
"""

from typing import Any

from pydantic import BaseModel


class SiteConfig(BaseModel):
    """内部模型。字段名 = system_config.name = JSON key，三位一体。

    这 47 个字段来自 FrontSiteConfigResult 里"从 DB 取值"的那部分，
    另外补了几个只有内部用的。后续步骤按需往上加。
    """

    # —— FrontSiteConfigResult 里来自 DB 的 47 个 ——
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
    # DB 里存的是 JSON 字符串（Java 靠 @JSONStringParse 解析）。第一版先原样收着，
    # 等做短链功能时再加 field_validator 解析。
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
    # AES 下载签名密钥（HEX）。★ 绝不能进 FrontSiteConfigResult —— 泄漏 = 谁都能伪造下载链接
    rsaHexKey: str | None = None

    @classmethod
    def from_rows(cls, rows: dict[str, str | None]) -> "SiteConfig":
        """把 system_config 的 {name: value} 灌成模型。

        对应 Java 的 SystemConfigService.getSystemConfig() 那整段反射。

        一行就够：Pydantic 的宽松模式本来就做 "true"->True、"5"->5 的转换，
        也就是 Java 那段 Convert.convert(field.getType(), strVal) 的活。
        """
        return cls.model_validate(rows)


class FrontSiteConfigResult(BaseModel):
    """响应契约, 漏字段的后果不是报错，是前端静默行为错误
    """

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
    debugMode: bool = False  # Java 读配置文件，这里先写死
    guest: bool = False  # 步骤 3 有了登录态再补


class FileListConfigRequest(BaseModel):
    """对应 FileListConfigRequest.java：POST /api/site/config/storage 的请求体。

    前端 useFileData.js 传的就是这三个字段（storageKey 必填，path 默认 "/"）。
    """

    storageKey: str
    path: str = "/"
    password: str | None = None
