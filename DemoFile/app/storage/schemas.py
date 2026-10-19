"""存储层对外输出的模型。对应 Java module/storage/model/result/ + model/bo/。"""

from datetime import datetime

from pydantic import BaseModel, field_serializer

from app.core.path_utils import concat
from app.storage.enums import FileType, UploadType


class FileItemResult(BaseModel):
    """对应 FileItemResult.java。字段名即前端读取的 JSON key。

    time 在 Java 中是 java.util.Date，由 Jackson 按
    spring.jackson.date-format=yyyy-MM-dd HH:mm:ss 序列化；这里通过
    field_serializer 在模型内完成同样格式，前端按字符串原样渲染。

    可空性是契约的一部分：文件夹的 size 为 None 而非 0（前端据此显示 "-"），
    文件夹也没有 url。
    """

    name: str
    time: datetime | None = None
    size: int | None = None
    type: FileType
    path: str | None = None
    url: str | None = None

    def get_full_path(self) -> str:
        """对应 Java 的 getFullPath()（那边标了 @JsonIgnore，不是响应字段）。"""
        return concat(self.path, self.name)

    @field_serializer("time")
    def _serialize_time(self, value: datetime | None) -> str | None:
        """将 time 序列化为 "yyyy-MM-dd HH:mm:ss"，与 Java 的全局 date-format 对齐。

        前端把 time 当字符串原样渲染，ISO 格式的 "2025-09-25T14:30:00" 会直接
        显示在表格中，因此必须在输出层完成格式化。
        """
        if value is None:
            return None
        return value.strftime("%Y-%m-%d %H:%M:%S")


class StorageSourceMetadata(BaseModel):
    """对应 StorageSourceMetadata.java：声明存储源支持的操作。

    布尔字段的默认值与 Java 类一致，子类只覆盖与默认不同的项。
    uploadType 在 Java 中没有默认值，必须由实现类提供。

    该对象必须始终完整返回给前端，缺字段会导致前端读取 undefined。
    """

    uploadType: UploadType | None = None
    supportRenameFolder: bool = True
    supportMoveFolder: bool = True
    supportCopyFolder: bool = True
    supportDeleteNotEmptyFolder: bool = True
    needCreateFolderBeforeUpload: bool = True


class StorageTypeInfo(BaseModel):
    """存储源类型的 JSON 形状 {key, description}。

    Java 的 StorageTypeEnum 使用 @JsonFormat(shape = OBJECT)，序列化为对象而非
    字符串。Python 的 str-Enum 默认输出字符串，所以需要这个包装类型；直接返回
    StorageType 会让前端按对象取 .key 时得到 undefined。
    """

    key: str
    description: str


class StorageSourceResult(BaseModel):
    """对应 StorageSourceResult.java：/api/storage/list 的列表项。

    前端（useHeaderStorageList.js）实际只使用 name 和 key，其余字段用于保持契约完整。
    """

    name: str | None = None
    key: str | None = None
    type: StorageTypeInfo
    searchEnable: bool | None = None
    defaultSwitchToImgMode: bool | None = None


class StorageSourceConfigResult(BaseModel):
    """对应 StorageSourceConfigResult.java：/api/site/config/storage 的响应。

    permission 和 metadata 必须始终有值。前端 storage-config.ts 直接
    updateFolderConfig(res.data)，permission 缺少某个 key 时对应按钮的显隐判断
    会读到 undefined。
    """

    readmeText: str | None = None
    readmeDisplayMode: str | None = None
    defaultSwitchToImgMode: bool | None = None
    # {操作名: 是否授权}，覆盖 FileOperatorType 全部 19 个 key
    permission: dict[str, bool]
    metadata: StorageSourceMetadata
    rootPath: str | None = None


class FileInfoResult(BaseModel):
    """对应 FileInfoResult.java：POST /api/storage/files 的 data。

    files 用于表格渲染，前端还会 unshift 一条返回上级目录的条目；
    passwordPattern 被前端存入"路径 → 密码"映射。密码功能未接入时它恒为 None，
    但字段必须存在：undefined 与 null 在前端不是一回事。
    """

    files: list[FileItemResult]
    passwordPattern: str | None = None
