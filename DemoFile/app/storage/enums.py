"""存储层枚举。对应 Java module/storage/model/enums/ 包。用到哪个抄哪个。"""

from enum import Enum


# 类型 key → 中文描述。Java 把两者写在枚举构造参数里（LOCAL("local", "本地存储")），
# Python 的 str-Enum 想让 ".value" 保持是纯 key，描述就放这张旁表。
_STORAGE_TYPE_DESCRIPTIONS = {
    "local": "本地存储",
}


class StorageType(str, Enum):
    """对应 StorageTypeEnum。

    值是 Java 侧的 key（"local"），**不是**枚举名 —— DB 的 storage_source.type
    存的是这个 key，/api/storage/list 的 type 字段要序列化成 {key, description} 对象。
    """

    LOCAL = "local"

    @property
    def description(self) -> str:
        return _STORAGE_TYPE_DESCRIPTIONS.get(self.value, self.value)


class FileType(str, Enum):
    """对应 FileTypeEnum。JSON 里是大写字符串，前端按 'FOLDER' / 'FILE' 判分支。"""

    FILE = "FILE"
    FOLDER = "FOLDER"


class UploadType(str, Enum):
    """对应 StorageSourceMetadata.UploadType（嵌在元数据里的内部枚举）。"""

    MICROSOFT = "MICROSOFT"
    PROXY = "PROXY"
    S3 = "S3"
    UPYUN = "UPYUN"


class FileOperatorType(str, Enum):
    """对应 FileOperatorTypeEnum 的 value 部分（19 个）。

    顺序照抄 Java —— build_permission_map 遍历它生成 {value: bool} 的权限表，
    顺序一致方便和 Java 侧对拍。Java 枚举里的中文描述是给后台管理界面用的，
    步骤 5 用不到，先不搬。
    """

    AVAILABLE = "available"
    NEW_FOLDER = "newFolder"
    UPLOAD = "upload"
    PREVIEW = "preview"
    DOWNLOAD = "download"
    BATCH_DOWNLOAD = "batchDownload"
    PACKAGE_DOWNLOAD = "packageDownload"
    COPY_DOWNLOAD_LINK = "copyDownloadLink"
    RENAME = "rename"
    COPY = "copy"
    MOVE = "move"
    DELETE = "delete"
    SEARCH = "search"
    LINK = "generateLink"
    SHORT_LINK = "generateShortLink"
    SHARE_LINK = "createShareLink"
    CUSTOM_SHARE_KEY = "customShareKey"
    IGNORE_PASSWORD = "ignorePassword"
    IGNORE_HIDDEN = "ignoreHidden"
