"""存储抽象层。对应 Java module/storage/service/base/ 包。

四层，每层只加一件事 —— **前三层一行文件 IO 都没有**：

    BaseFileService(ABC)            15 个方法 = 所有存储源的公共能力清单（接口）
    AbstractBaseFileService         实例状态 + init 守卫 + 用户根目录解析
    AbstractProxyTransferService    服务端中转的 URL 拼装（/pd、/file/upload）
    LocalServiceImpl                真正碰文件系统

以后加 S3 实现时，上面三层的活全是白送的 —— 这就是抽象的价值。抽象方法其实只有
4 个：_init / get_storage_source_metadata / upload_file / download_to_stream。

命名约定：**方法 snake_case，数据字段保持 Java 原名（camelCase）**。
字段名是线上契约（DB 列名 / JSON key / 前端读的 key），方法名不是。

★ 路径契约（本文件最重要的东西，写错 = 越权访问）：

    相对入参族：file_list / get_file_item / new_folder / delete_* / rename_* /
                copy_* / move_* / upload_file
        入参是**相对用户根**的路径（"/"、"/foo"）。
        实现内部**要**调 get_current_user_base_path() 拼出真实路径。

    绝对入参族：get_download_url / download_to_stream
        入参**已经含用户根**（调用方拼好的）。
        实现内部**绝不**再拼 —— 它们的调用链（直链 / 短链 / 分享 / 代理回源）跑在
        匿名线程或跨用户上下文里，那时 get_current_user_base_path() 拿到的是匿名用户的
        根目录，二次拼接 = 下错文件 / 404。Java 仓库的 469b9d4 就是修这个 bug 的提交。

    同一个类里两种写法并存，这是刻意的。
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
        """★ 绝对入参：path_and_name **已含用户根**，实现里不得再拼 get_current_user_base_path()。"""

    @abstractmethod
    def get_storage_type(self) -> StorageType: ...

    @abstractmethod
    def destroy(self) -> None: ...


class AbstractBaseFileService(BaseFileService, Generic[P]):
    """对应 AbstractBaseFileService.java：实例状态 + 初始化 + 用户根目录解析。

    「一存储源一实例」的载体就是这里的状态：param 里装着 filePath、domain 这些
    来自 DB 的配置。Java 靠 @Scope(PROTOTYPE) 保证每个存储源一个对象，
    Python 不需要框架帮忙 —— 步骤 5 的 loader 每个存储源 new 一个就是了。
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
        """对应 Java 的 init(name, storageId, param)（我们多一个 storage_key）。

        两道守卫，照抄：
          - 字段都已被设置 → 重复初始化，抛 IllegalStateException
          - 任一入参为空   → 抛 IllegalStateException
        ⚠️ 陷阱：Java 的 ObjUtil.hasEmpty 对数字 0 判 false（不算空），
        Python 的 `not storage_id` 会把 0 当成空 —— 用 `is None`，别用真值判断。

        最后调子类的 _init()（Java 里是那个无参抽象 init()，Python 没法同名重载，
        改成下划线前缀的内部钩子）。

        TODO 写实现
        """
        # raise NotImplementedError
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
        """对应 testConnection()：能列出根目录就算连接成功。

        启动期调用 —— 那会儿没有请求上下文，所以下面 get_current_user_base_path()
        里"未初始化则强制用管理员 id"那条分支是必须的，不是怪癖。

        TODO：self.file_list("/")；成功则 is_initialized = True；
              任何异常包成 BizException(ErrorCode.BIZ_STORAGE_INIT_ERROR,
              f"初始化异常, 错误信息为: {e}")（Java 是 InitializeStorageSourceBizException）。
        """
        # raise NotImplementedError
        try:
            self.file_list("/")
            self.is_initialized=True
        except Exception as e:
            raise BizException(ErrorCode.BIZ_STORAGE_INIT_ERROR, f"初始化失败,错误信息为: {e}") from e

    def get_current_user_base_path(self) -> str:
        """对应 getCurrentUserBasePath()。★ 只有"相对入参族"的方法才准调它。

        Java 算法（顺序别换）：
          ① 分享访问优先：ShareAccessContext.isShareAccess() → getShareBasePath()
             （本步跳过，等做分享那步再接 —— 留个 TODO 注释占位）
          ② user_id = ZFileAuthUtil.getCurrentUserId()
             → 这边对应 app.core.context.get_current_user_id()；
               contextvar 是 None（不在请求上下文里）时兜底 ANONYMOUS_ID
          ③ if not self.is_initialized: user_id = ADMIN_ID   ← 见 test_connection 注释
          ④ root_path = self._lookup_user_root_path(user_id)
             查不到 或 为空 → "/"

        TODO 写实现
        """
        # raise NotImplementedError
        user_id = context.get_current_user_id()
        if user_id is None:
            user_id = ANONYMOUS_ID
        if not self.is_initialized:
            user_id = ADMIN_ID
        return self._lookup_user_root_path(user_id) or "/"
    
    def _lookup_user_root_path(self, user_id: int) -> str | None:
        """查 user_storage_source 表拿 (user_id, storage_id) 的 root_path。

        对应 Java 的 userStorageSourceService.getByUserIdAndStorageId()。

        规格：
          - 无授权行 或 root_path 为空 → 返回 None（调用方 get_current_user_base_path 兜底 "/"）
          - 短会话：`with SessionLocal() as db:` —— service 实例是长期对象、被线程池共享，
            **绝不能**把 Session 存成实例属性
          - storage_id 用 self.storage_id（已 init，非 None → 记得断言收窄）
          - 差异：Java 对查询结果有缓存，我们先不缓存（SQLite 本地读，先正确后优化），
            把这条差异写进注释
          - 测试里这个方法会被 make_service 整个覆写成常量 lambda —— 所以本实现
            改了也不影响 34 条 pytest，放心改

        TODO 写实现
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
        """对应 getProxyDownloadUrl(pathAndName, useParamDomain)。产出形如
        `{base_url}/pd/{storageKey}/{encode(path)}?signature={sig}`。

        Java 的四步：
          ① 隐藏文件（basename 以 '.' 开头）特殊处理：文件名挪到 `?filename=` 查询参数，
             URL 路径退成父目录。**原因**：`/pd/xxx/.env` 会被静态资源安全规则拦掉。
             （计划里说第一版可跳过 —— 跳过就在这儿留 TODO 写清原因）
          ② 签名：proxyPrivate ? 带过期时间 : 永久签名。
             ⚠️ 签名对象是**完整的 path_and_name（带文件名）**，不是 ① 截断后的 path。
             本步先调 self._sign_download_url()，它步骤 7 才有真实现。
          ③ URL：use_param_domain 且 param.domain 非空 → param.domain + encode(path)；
             否则 → self._get_base_url() + "/pd" + storage_key + encode(path)
          ④ 有查询串就拼到 URL 末尾（"?" + query）

        TODO 写实现
        """
        # raise NotImplementedError
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
        """对应 getProxyUploadUrl(path, name)：拼 `/file/upload/{storageKey}/{path/name}`。

        隐藏文件同样走 `?filename=` 形式（Java 122-125 行），但这里**没有签名**。
        与下载不同的另一点：fullPath 是 concat(path, name)。

        TODO 写实现
        """
        # raise NotImplementedError
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
        """对应 SystemConfigService.getAxiosFromDomainOrSetting()。拼下载地址用。

        三级优先（照抄 Java，顺序别换）：
          ① system_config.forceBackendAddress 非空 → 用它
             （读法：get_site_config(db).forceBackendAddress；storage 层到 modules 层是
               向上依赖，用**函数内延迟 import**，别写在文件顶部）
          ② context.get_axios_from()      ← 请求头 axios-from，前端 zfile.config.json 的 baseUrl
          ③ context.get_request_base_url() ← 请求自身地址（反向代理场景靠 X-Forwarded-*）

        启动期（test_connection 触发的 URL 拼装）②③ 都是 None → 返回 None，
        concat 会跳过空段得到相对路径（无害）。

        差异：Java 对 system_config 有缓存，我们每次读 DB（先正确后优化）—— 写进注释。
        测试里覆写它（如返回 "http://127.0.0.1:8080"），实现改了不影响 34 条 pytest。
        """
        # raise NotImplementedError
        from app.modules.config.service import get_site_config
        with SessionLocal() as db:
            force_backend_address = get_site_config(db).forceBackendAddress
        if force_backend_address and force_backend_address.strip():
            return force_backend_address
        return context.get_axios_from() or context.get_request_base_url()

    def _sign_download_url(self, path_and_name: str) -> str:
        """下载签名。对应 ProxyDownloadUrlUtils.generatorSignature / generatorPermanentSignature。

        调用点：本类 get_proxy_download_url() —— 列表里每个文件项的 url 都经过这里。

        规格（照 Java getProxyDownloadUrl 79-81 行）：
          - param.proxyPrivate（默认 True）→ sign.generator_signature(
                self.storage_id, path_and_name, self.param.proxyTokenTime, hex_key)
          - 否则 → sign.generator_permanent_signature(self.storage_id, path_and_name, hex_key)
          - hex_key 从 modules.config.service.get_aes_hex_key_or_generate(db) 来：
                with SessionLocal() as db:  hex_key = get_aes_hex_key_or_generate(db)
            storage 层 → modules 层是向上依赖，照 _get_base_url 的先例用**函数内延迟 import**
          - assert self.storage_id is not None（init 后必非空）

        ★ 签名对象就是入参 path_and_name 原样（含文件名、含用户根）—— 它必须和 URL 里
          encode 前的那段路径逐字符一致，校验端（7b）靠同一段路径比对。别在这里做任何裁剪。
        """
        # raise NotImplementedError
        # return "TODO-signature"
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
        """上传文件。★ 绝对入参（步骤 6 的上传功能才会用到）。"""

    @abstractmethod
    def download_to_stream(self, path_and_name: str,range_header: str | None = None):
        """代理回源下载，返回 HttpResponse。★ 绝对入参，**绝不**再拼用户根目录。

        步骤 7 实现（含 HTTP Range / 206）。
        """
