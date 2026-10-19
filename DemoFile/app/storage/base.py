"""存储抽象层。对应 Java module/storage/service/base/ 包。

四层，前三层不涉及文件 IO：

    BaseFileService(ABC)            所有存储源的公共能力清单（15 个方法）
    AbstractBaseFileService         实例状态 + init 守卫 + 用户根目录解析
    AbstractProxyTransferService    服务端中转的 URL 拼装（/pd、/file/upload）
    LocalServiceImpl                实际文件系统实现

新增 S3 等实现时，前三层能力可直接复用。抽象方法只有 4 个：
_init / get_storage_source_metadata / upload_file / download_to_stream。

命名约定：方法使用 snake_case，数据字段保持 Java 原名（camelCase）。
字段名是线上契约（DB 列名 / JSON key / 前端读取的 key），方法名不是。

路径契约（本文件最关键的部分，写错会导致越权访问）：

    相对入参族：file_list / get_file_item / new_folder / delete_* / rename_* /
                copy_* / move_* / upload_file
        入参是相对用户根的路径（"/"、"/foo"），实现内部需要调用
        get_current_user_base_path() 拼出真实路径。

    绝对入参族：get_download_url / download_to_stream
        入参已包含用户根（调用方拼接完成），实现内部绝不能再拼。它们的调用链
        （直链 / 短链 / 分享 / 代理回源）运行在匿名线程或跨用户上下文中，此时
        get_current_user_base_path() 返回匿名用户根目录，二次拼接会导致下错文件
        或 404。Java 仓库的提交 469b9d4 即为修复该问题。

    同一个类中两种写法并存，这是刻意设计。
"""

from abc import ABC, abstractmethod
from typing import Generic, TypeVar

from sqlalchemy import select

from app.storage.enums import StorageType
from app.storage.schemas import FileItemResult, StorageSourceMetadata
from app.core import context
from app.core.db import SessionLocal
from app.models.storage import UserStorageSource
from app.models.user import ANONYMOUS_ID, ADMIN_ID

from urllib.parse import urlencode
from app.core.errors import BizException, ErrorCode
from app.core.path_utils import concat, encode_ignore_slashes, get_name, get_parent_path
from app.storage.params import ProxyTransferParam

P = TypeVar("P")
ProxyP = TypeVar("ProxyP", bound=ProxyTransferParam)


class BaseFileService(ABC):
    """对应 BaseFileService.java：能力清单，没有一行实现。"""

    @abstractmethod
    def file_list(self, folder_path: str) -> list[FileItemResult]:
        """列出目录下的文件和文件夹。folder_path 相对用户根（'/'、'/foo'）。"""

    @abstractmethod
    def get_file_item(self, path_and_name: str) -> FileItemResult | None:
        """取单个文件/文件夹信息，不存在返回 None。path_and_name 相对用户根。"""

    @abstractmethod
    def new_folder(self, path: str, name: str) -> bool:
        """在 path（相对用户根）下新建名为 name 的文件夹。"""

    @abstractmethod
    def delete_file(self, path: str, name: str) -> bool: ...

    @abstractmethod
    def delete_folder(self, path: str, name: str) -> bool: ...

    @abstractmethod
    def copy_file(self, path: str, name: str, target_path: str, target_name: str) -> bool: ...

    @abstractmethod
    def copy_folder(self, path: str, name: str, target_path: str, target_name: str) -> bool: ...

    @abstractmethod
    def move_file(self, path: str, name: str, target_path: str, target_name: str) -> bool: ...

    @abstractmethod
    def move_folder(self, path: str, name: str, target_path: str, target_name: str) -> bool: ...

    @abstractmethod
    def rename_file(self, path: str, name: str, new_name: str) -> bool: ...

    @abstractmethod
    def rename_folder(self, path: str, name: str, new_name: str) -> bool: ...

    @abstractmethod
    def get_upload_url(self, path: str, name: str, size: int | None) -> str:
        """上传地址。path / name 相对用户根。"""

    @abstractmethod
    def get_download_url(self, path_and_name: str) -> str:
        """下载地址。绝对入参：path_and_name 已含用户根，实现内不得再拼接 get_current_user_base_path()。"""

    @abstractmethod
    def get_storage_type(self) -> StorageType: ...

    @abstractmethod
    def destroy(self) -> None: ...


class AbstractBaseFileService(BaseFileService, Generic[P]):
    """对应 AbstractBaseFileService.java：实例状态 + 初始化 + 用户根目录解析。

    「一存储源一实例」的状态载体：param 保存 filePath、domain 等来自数据库的配置。
    Java 通过 @Scope(PROTOTYPE) 保证每个存储源一个对象；Python 不需要框架，
    loader 在装配时逐个 new 即可。
    """

    def __init__(self) -> None:
        self.name: str | None = None
        self.storage_id: int | None = None
        # Java 没有这个字段：那边每次要 key 都去 DB 查（storageSourceService.findStorageKeyById）。
        # key 是随存储源定下来的常量，跟 name / storageId 同性质，装配时给一次就够。
        self.storage_key: str | None = None
        self.param: P | None = None
        self.is_initialized: bool = False

    def init(self, name: str, storage_id: int, storage_key: str, param: P) -> None:
        """对应 Java 的 init(name, storageId, param)（这里多一个 storage_key）。

        两个守卫与 Java 一致：
          - 字段已被设置 → 重复初始化，抛 IllegalStateException
          - 任一入参为空 → 抛 IllegalStateException

        注意：Java 的 ObjUtil.hasEmpty 对数字 0 判定为 false（不算空），而 Python 的
        `not storage_id` 会把 0 视为空，因此使用 `is None` 判断。

        最后调用子类的 _init()（Java 中为无参抽象 init()；Python 无法同名重载，
        改为下划线前缀的内部钩子）。
        """
        if self.name is not None or self.storage_id is not None or self.storage_key is not None or self.param is not None:
            raise RuntimeError("请勿重复初始化")
        if not name or storage_id is None or not storage_key or param is None:
            raise RuntimeError("初始化参数不能为空")

        self.name = name
        self.storage_id = storage_id
        self.storage_key = storage_key
        self.param = param
        self._init()

    @abstractmethod
    def _init(self) -> None:
        """对应 Java 抽象 init()：子类自己的初始化（本地存储 = 校验 filePath 目录存在）。"""

    def test_connection(self) -> None:
        """对应 testConnection()：能列出根目录即视为连接成功。

        启动期调用，此时没有请求上下文，因此 get_current_user_base_path() 中
        "未初始化则强制使用管理员 id"的分支是必需的。
        """
        try:
            self.file_list("/")
            self.is_initialized=True
        except Exception as e:
            raise BizException(ErrorCode.BIZ_STORAGE_INIT_ERROR, f"初始化失败,错误信息为: {e}") from e

    def get_current_user_base_path(self) -> str:
        """对应 getCurrentUserBasePath()。只有"相对入参族"的方法可以调用它。

        算法（顺序不可调换）：
          1. 分享访问优先：ShareAccessContext.isShareAccess() → getShareBasePath()
             （分享功能尚未实现，待接入时补齐）
          2. user_id = context.get_current_user_id()；contextvar 为 None（不在请求
             上下文中）时兜底 ANONYMOUS_ID
          3. if not self.is_initialized: user_id = ADMIN_ID（见 test_connection）
          4. root_path = self._lookup_user_root_path(user_id)；查不到或为空 → "/"
        """
        user_id = context.get_current_user_id()
        if user_id is None:
            user_id = ANONYMOUS_ID
        if not self.is_initialized:
            user_id = ADMIN_ID
        return self._lookup_user_root_path(user_id) or "/"
    
    def _lookup_user_root_path(self, user_id: int) -> str | None:
        """查询 user_storage_source 中 (user_id, storage_id) 的 root_path。

        对应 Java userStorageSourceService.getByUserIdAndStorageId()。

        无授权行或 root_path 为空 → 返回 None（由调用方兜底 "/"）。
        使用短会话 `with SessionLocal() as db:`：service 实例是长期对象、被线程池
        共享，绝不能把 Session 存为实例属性。
        storage_id 使用 self.storage_id（已 init，非 None，用断言收窄）。
        与 Java 的差异：Java 对查询结果有缓存，这里暂不缓存（SQLite 本地读取，
        优先正确性）。
        """
        assert self.storage_id is not None

        with SessionLocal() as db:
            root_path = db.scalar(
                select(UserStorageSource.root_path).where(
                    UserStorageSource.user_id == user_id,
                    UserStorageSource.storage_source_id == self.storage_id,
                )
            )
        return root_path or None

    @abstractmethod
    def get_storage_source_metadata(self) -> StorageSourceMetadata:
        """对应 getStorageSourceMetadata()：告诉前端这个存储源支持哪些操作。"""


    def destroy(self) -> None:
        """对应 Java 的 destroy()：释放连接资源。本地存储没资源可放，空实现。"""
        return None


class AbstractProxyTransferService(AbstractBaseFileService[ProxyP]):
    """对应 AbstractProxyTransferService.java：服务端中转的上传/下载 URL 拼装。

    只被 LOCAL / FTP / SFTP / WebDAV 这类"要经过服务端中转"的存储源继承；
    S3 那种前端直传的走另一条路。
    """

    #: 代理下载 URL 前缀。对应 Java PROXY_DOWNLOAD_LINK_PREFIX
    PROXY_DOWNLOAD_LINK_PREFIX = "/pd"
    #: 代理上传 URL 前缀。对应 Java PROXY_UPLOAD_LINK_PREFIX
    PROXY_UPLOAD_LINK_PREFIX = "/file/upload"

    def get_proxy_download_url(self, path_and_name: str, use_param_domain: bool = False) -> str:
        """生成代理下载地址 `{base_url}/pd/{storageKey}/{encode(path)}?signature={sig}`。

        隐藏文件（basename 以 '.' 开头）把文件名挪进 `?filename=`，URL 路径退到父目录：
        `/pd/xxx/.env` 会被静态资源安全规则拦截。签名对象始终是完整的 path_and_name
        （含文件名），而不是截断后的父目录——签名端和校验端必须逐字符一致。

        use_param_domain 且 param.domain 非空时直接使用配置的域名，否则回落为
        _get_base_url() + 代理前缀。
        """
        path = path_and_name
        query: dict[str, str] = {}
        filename = get_name(path_and_name)
        if filename and filename.startswith("."):
            query["filename"] = filename
            path = get_parent_path(path_and_name)
        query["signature"] = self._sign_download_url(path_and_name)

        if not use_param_domain or not self.param.domain:
            url = concat(
                self._get_base_url(),
                self.PROXY_DOWNLOAD_LINK_PREFIX,
                self.storage_key,
                encode_ignore_slashes(path),
            )
        else:
            url = concat(self.param.domain, encode_ignore_slashes(path))

        if query:
            url = url + "?" + urlencode(query)
        return url

    def get_proxy_upload_url(self, path: str, name: str) -> str:
        """生成代理上传地址 `/file/upload/{storageKey}/{path}/{name}`。

        隐藏文件同样走 `?filename=` 形式，但上传没有签名。fullPath 是
        concat(path, name)，与下载接口直接接收 path_and_name 不同。
        """
        full_path = concat(path,name)
        query:dict[str,str] = {}

        if name.startswith("."):
            query["filename"] = name
            full_path = path
        url = concat(
            self._get_base_url(),
            self.PROXY_UPLOAD_LINK_PREFIX,
            self.storage_key,
            encode_ignore_slashes(full_path),
        )
        if query:
            url = url + "?" + urlencode(query)
        return url

    def _get_base_url(self) -> str | None:
        """解析拼 URL 用的后端根地址，对应 SystemConfigService.getAxiosFromDomainOrSetting()。

        优先级固定为：system_config.forceBackendAddress → 请求头 axios-from（前端
        zfile.config.json 的 baseUrl）→ 当前请求地址（反向代理场景依赖 X-Forwarded-*）。

        storage 层引用 modules.config 属于向上依赖，沿用函数内延迟 import。
        system_config 每次读 DB，未做缓存：Java 有缓存，这里先保证正确性。
        启动期 test_connection 也会调用本方法，此时后两级均为 None，返回 None 后
        concat 跳过空段得到相对路径。
        """
        from app.modules.config.service import get_site_config
        with SessionLocal() as db:
            force_backend_address = get_site_config(db).forceBackendAddress
        if force_backend_address and force_backend_address.strip():
            return force_backend_address
        return context.get_axios_from() or context.get_request_base_url()

    def _sign_download_url(self, path_and_name: str) -> str:
        """生成下载签名，对应 ProxyDownloadUrlUtils.generatorSignature。

        proxyPrivate（默认 True）走带过期时间的签名，否则走永久签名；AES 密钥
        每次从 system_config 读取。storage 层引用 modules.config 为向上依赖，
        用函数内延迟 import。

        签名对象是入参 path_and_name 原样（含文件名、含用户根），必须与 URL 中
        encode 前的路径逐字符一致——代理端用同一字符串校验，这里不能做任何裁剪。
        """
        from app.core.sign import generator_permanent_signature, generator_signature
        from app.modules.config.service import get_aes_hex_key_or_generate

        assert self.storage_id is not None

        with SessionLocal() as db:
            hex_key = get_aes_hex_key_or_generate(db)

            if self.param.proxyPrivate:
                return generator_signature(self.storage_id,path_and_name,self.param.proxyTokenTime,hex_key)
            return generator_permanent_signature(self.storage_id,path_and_name,hex_key)

    @abstractmethod
    def upload_file(self, path_and_name: str, input_stream, size: int | None) -> None:
        """上传文件。绝对入参：path_and_name 已包含用户根。"""

    @abstractmethod
    def download_to_stream(self, path_and_name: str, range_header: str | None = None):
        """代理回源下载，返回可流式响应的 Response，支持 HTTP Range。

        绝对入参：path_and_name 已包含用户根，实现内不得再拼接用户根。
        """
