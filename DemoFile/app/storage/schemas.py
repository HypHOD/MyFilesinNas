"""存储层对外输出的模型。对应 Java module/storage/model/result/ + model/bo/。"""

from datetime import datetime

from pydantic import BaseModel, field_serializer

from app.core.path_utils import concat
from app.storage.enums import FileType, UploadType


class FileItemResult(BaseModel):
    """对应 FileItemResult.java。字段名 = 前端读的 JSON key。

    ⚠️ time 的坑：Java 是 java.util.Date，由 Jackson 按
    spring.jackson.date-format=yyyy-MM-dd HH:mm:ss 序列化。
    Python 这边先存 datetime，**序列化器步骤 6 再加** ——
    现在直出会是 ISO 的 2025-09-25T14:30:00，而前端是原样渲染这个字符串的。

    字段的可空性是刻意的：
      - 文件夹的 size 必须是 None（不是 0），前端靠 `type === 'FOLDER' && !size` 显示 "-"
      - 文件夹没有 url（只有文件才有下载地址）
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
        """★ time 的序列化格式必须是 "yyyy-MM-dd HH:mm:ss"，不是 ISO。

        用途：前端把 time 当字符串**原样渲染**（表格列直接显示）—— 输出 ISO 的
        "2025-09-25T14:30:00"，用户就看到一串带 T 的怪东西。Java 靠 Jackson 全局
        date-format 配置干这事，我们在模型上局部干。

        规格：pydantic v2 的 @field_serializer("time")；value 为 None → None；
              否则 value.strftime("%Y-%m-%d %H:%M:%S")

        TODO 写实现
        """
        # raise NotImplementedError
        if value is None:
            return None
        return value.strftime("%Y-%m-%d %H:%M:%S")


class StorageSourceMetadata(BaseModel):
    """对应 StorageSourceMetadata.java：告诉前端这个存储源支持哪些操作。

    下面 4 个 bool 的默认值就是 Java 类里的默认值，**子类只覆盖和默认不同的项**。
    uploadType 在 Java 里没有默认值（null），必须由实现类给。

    ⚠️ 步骤 5 起这个对象必须**永远**返回给前端，缺字段前端直接崩。
    """

    uploadType: UploadType | None = None
    supportRenameFolder: bool = True
    supportMoveFolder: bool = True
    supportCopyFolder: bool = True
    supportDeleteNotEmptyFolder: bool = True
    needCreateFolderBeforeUpload: bool = True


class StorageTypeInfo(BaseModel):
    """存储源类型的 JSON 形状：{key, description}。

    Java 的 StorageTypeEnum 上有 @JsonFormat(shape = OBJECT)，序列化出来是对象而不是
    "local" 字符串。Python 的 str-Enum 默认序列化成字符串，所以需要这个壳 ——
    ★ 别图省事直接塞 StorageType，前端拿到字符串会当对象取 .key，得到 undefined。
    """

    key: str
    description: str


class StorageSourceResult(BaseModel):
    """对应 StorageSourceResult.java：/api/storage/list 的列表项。

    前端（useHeaderStorageList.js）只用 name / key，其余是契约完整性。
    """

    name: str | None = None
    key: str | None = None
    type: StorageTypeInfo
    searchEnable: bool | None = None
    defaultSwitchToImgMode: bool | None = None


class StorageSourceConfigResult(BaseModel):
    """对应 StorageSourceConfigResult.java：/api/site/config/storage 的响应。

    permission 和 metadata **必须永远有值**（不是可选字段）：
      前端 storage-config.ts 拿到后直接 updateFolderConfig(res.data)，
      permission 里少一个 key，对应按钮的显隐判断读到 undefined 就开始抽风。
    """

    readmeText: str | None = None
    readmeDisplayMode: str | None = None
    defaultSwitchToImgMode: bool | None = None
    # {操作名: 有没有权限}，穷举 FileOperatorType 全部 19 个 key
    permission: dict[str, bool]
    metadata: StorageSourceMetadata
    rootPath: str | None = None


class FileInfoResult(BaseModel):
    """对应 FileInfoResult.java：POST /api/storage/files 的 data。

    用途：文件列表接口的响应体 —— files 给表格渲染（前端 useFileData.js:108 读
    response.data.files，:111 还会往里 unshift 一条 BACK 项），passwordPattern 被
    前端存进"路径 → 密码"表（:99 putPathPwd）。密码功能未做时它恒为 None，
    但**字段必须存在**（前端会读，undefined 和 null 不是一回事）。
    """

    files: list[FileItemResult]
    passwordPattern: str | None = None
