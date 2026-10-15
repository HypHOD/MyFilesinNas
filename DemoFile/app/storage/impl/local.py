"""本地存储实现。对应 LocalServiceImpl.java —— 计划里唯一要求"逐行读"的文件。

实现顺序（每写完一步跑一次 pytest，别一次写完再跑 —— 报错会糊成一团）：

    1. _init / get_storage_type / get_storage_source_metadata   最简，先把对象构造出来
    2. _to_file_item + file_list + get_file_item                列表能出来
    3. get_download_url                                         url 字段能出来
    4. new_folder / delete_* / rename_* / copy_* / move_*       文件操作
    5. upload_file / download_to_stream                         留到步骤 6 / 7，先保持 NotImplementedError
"""

from app.storage.base import AbstractProxyTransferService
from app.storage.enums import FileType, StorageType, UploadType
from app.storage.params import LocalParam
from app.storage.schemas import FileItemResult, StorageSourceMetadata

import shutil
import mimetypes
from pathlib import Path
from fastapi.responses import FileResponse
from app.core.stream import build_file_response
from datetime import datetime

from app.core.errors import BizException, ErrorCode
from app.core.path_utils import concat, encode_ignore_slashes, get_parent_path
from app.storage.base import AbstractProxyTransferService
from app.storage.enums import FileType, StorageType, UploadType
from app.storage.params import LocalParam
from app.storage.schemas import FileItemResult, StorageSourceMetadata
from app.storage.security import check_name_security, check_path_security


_OP_COPY = "copy"
_OP_MOVE = "move"
_OP_RENAME = "rename"


class LocalServiceImpl(AbstractProxyTransferService[LocalParam]):
    """对应 LocalServiceImpl.java（@Service + @Scope(PROTOTYPE)，那两行注解在 Python 里
    就是"步骤 5 的 loader 每个存储源 new 一个本类实例"）。
    """

    def _init(self) -> None:
        """对应 LocalServiceImpl.init()：校验 param.filePath 存在。

        报错信息照抄 Java（运维靠这个字符串定位问题）：
            f"文件路径:「{绝对路径}」不存在, 请检查是否填写正确."
        异常：BizException(ErrorCode.BIZ_STORAGE_INIT_ERROR, msg)
        （Java 的全局处理器还会再加个"存储源初始化失败："前缀，Python 这边 msg 会原样发出。）

        TODO 写实现
        """
        # raise NotImplementedError
        file_path = Path(self.param.filePath)
        if not file_path.exists():
            raise BizException(ErrorCode.BIZ_STORAGE_INIT_ERROR,f"文件路径: 「{file_path.resolve()}」不存在,请检查填写是否正确.")
        

    def get_storage_type(self) -> StorageType:
        """对应 getStorageTypeEnum()。答案就在 Java 文件里，一行。"""
        # raise NotImplementedError
        return StorageType.LOCAL

    def get_storage_source_metadata(self) -> StorageSourceMetadata:
        """对应 getStorageSourceMetadata()：只覆盖和默认值**不同**的两项。

        Java 原代码（336-341 行）：
            uploadType = PROXY
            needCreateFolderBeforeUpload = false
        其余 4 个 bool 保持 StorageSourceMetadata 的默认值 true，不要重复写。

        TODO 写实现
        """
        # raise NotImplementedError
        return StorageSourceMetadata(
            uploadType=UploadType.PROXY,
            needCreateFolderBeforeUpload=False,
        )

    # ── 相对入参族（内部要拼用户根目录）────────────────────────────────

    def file_list(self, folder_path: str) -> list[FileItemResult]:
        """对应 fileList(folderPath)。

        Java 步骤：
          ① check_path_security(folder_path)
          ② full_path = concat(param.filePath, self.get_current_user_base_path(), folder_path)
          ③ 不是"已存在的目录" → BizException(ErrorCode.BIZ_FOLDER_NOT_EXIST)
          ④ 遍历目录 → _to_file_item(每项, folder_path)
             ⚠️ 传下去的 folder_path 是**父目录**（原样传，不是 full_path）
          ⑤ 目录为空 → 返回空 list（Java 里 listFiles() 返回 null 时也是空 list，别抛异常）

        TODO 写实现
        """
        # raise NotImplementedError
        check_path_security(folder_path)

        full_path = concat(self.param.filePath, self.get_current_user_base_path(), folder_path)
        folder = Path(full_path)
        if not (folder.exists() and folder.is_dir()):
            raise BizException(ErrorCode.BIZ_FILE_NOT_EXIST)

        try:
            entries = list(folder.iterdir())
        except OSError:
            return []
        return [self._to_file_item(entry,folder_path) for entry in entries]
    

    def get_file_item(self, path_and_name: str) -> FileItemResult | None:
        """对应 getFileItem(pathAndName)。

        和 file_list 的两处不同：
          - 不存在返回 **None**（不抛异常）
          - 传给 _to_file_item 的 folder_path 是 get_parent_path(path_and_name)，不是入参本身

        TODO 写实现
        """
        # raise NotImplementedError
        check_path_security(path_and_name)

        full_path = concat(self.param.filePath, self.get_current_user_base_path(), path_and_name)
        file = Path(full_path)
        if not file.exists():
            return None
        return self._to_file_item(file, get_parent_path(path_and_name))
        
    def new_folder(self, path: str, name: str) -> bool:
        """对应 newFolder(path, name)：check path + check name → concat → mkdir。

        Java 用 FileUtil.mkdir（返回目录对象或 null）。Python 侧注意：
        要能处理"父目录不存在"，Java 的 mkdir 是**递归**创建（hutool 语义）。

        TODO 写实现
        """
        # raise NotImplementedError
        check_path_security(path)
        check_name_security(name)

        folder = Path(concat(self.param.filePath, self.get_current_user_base_path(), path, name))
        folder.mkdir(parents=True, exist_ok=True)
        return folder.is_dir()


    def delete_file(self, path: str, name: str) -> bool:
        """对应 deleteFile(path, name)：check → concat → del。

        ⚠️ 这个方法是**文件和目录共用**的（delete_folder 直接转调它），
        因为要支持"删除非空文件夹"——所以不能只用 os.remove，
        是目录时得走 shutil.rmtree。

        TODO 写实现
        """
        # raise NotImplementedError
        check_path_security(path)
        check_name_security(name)
        target = Path(concat(self.param.filePath, self.get_current_user_base_path(), path, name))
        if not target.exists():
            return True # 与hutool保持一致
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
        # return self.delete_file(path,name)
        return not target.exists()


    def delete_folder(self, path: str, name: str) -> bool:
        """对应 deleteFolder()：一行 —— 转调 delete_file。

        TODO 写实现
        """
        # raise NotImplementedError
        check_path_security(path)
        check_name_security(name)
        target = Path(concat(self.param.filePath, self.get_current_user_base_path(), path, name))
        if not target.exists():
            return True # 与hutool保持一致
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
        # return self.delete_folder(path,name)
        return not target.exists()


    def rename_file(self, path: str, name: str, new_name: str) -> bool:
        """对应 renameFile()：转调 _operate_file(path, name, path, new_name, RENAME)。"""
        # raise NotImplementedError
        return self._operate_file(path,name,path,new_name,_OP_RENAME)

    def rename_folder(self, path: str, name: str, new_name: str) -> bool:
        """同 rename_file（Java 里两个方法体一模一样）。"""
        # raise NotImplementedError
        return self._operate_file(path,name,path,new_name,_OP_RENAME)

    def copy_file(self, path: str, name: str, target_path: str, target_name: str) -> bool:
        """对应 copyFile()：_operate_file(..., COPY)。"""
        # raise NotImplementedError
        return self._operate_file(path,name,target_path,target_name,_OP_COPY)

    def copy_folder(self, path: str, name: str, target_path: str, target_name: str) -> bool:
        """同 copy_file。"""
        # raise NotImplementedError
        return self._operate_file(path,name,target_path,target_name,_OP_COPY)

    def move_file(self, path: str, name: str, target_path: str, target_name: str) -> bool:
        """对应 moveFile()：_operate_file(..., MOVE)。"""
        # raise NotImplementedError
        return self._operate_file(path,name,target_path,target_name,_OP_MOVE)


    def move_folder(self, path: str, name: str, target_path: str, target_name: str) -> bool:
        """同 move_file。"""
        # raise NotImplementedError
        return self._operate_file(path,name,target_path,target_name,_OP_MOVE)

    def _operate_file(self, path: str, name: str, new_path: str, new_name: str, operator: str) -> bool:
        """对应 operateFile()，4 种操作共用的核心。Java 189-216 行。

        规格：
          ① check_path_security(path, new_path); check_name_security(name, new_name)
          ② 原地不动（path == new_path 且 name == new_name）→ 直接 return True，
             不做任何文件操作（Java 是为了避开某些协议下"自己重命名自己"的报错）
          ③ src = concat(param.filePath, 用户根, path, name)
             ★ append_name = "" if COPY else new_name
                  —— 复制时目标是**目录**（保留原名），移动/重命名时目标是**完整新路径**
             dst = concat(param.filePath, 用户根, new_path, append_name)
          ④ 按 operator 分派：MOVE → shutil.move / COPY → shutil.copy2 / RENAME → 就地改名
             （Java 用 hutool FileUtil.move(copy/rename)）

        ⚠️ 与 Java 的差异，自己定并写进注释：Java 这三个 FileUtil 方法**失败返回 false 不抛异常**，
        Python 的 shutil 失败会抛。要么 try/except 成 False（贴近 Java），
        要么让它冒泡给全局异常处理器（前端体验更好，但和 Java 行为不同）。

        operator 用字符串常量还是 Enum？FileOperatorTypeEnum 有 17 个值，
        这里只用到 3 个 —— 建议先用 3 个模块级字符串常量，步骤 5 做权限时才需要整个枚举。

        TODO 写实现
        """
        # raise NotImplementedError
        check_name_security(name,new_name)
        check_path_security(path,new_path)
        if path==new_path and name == new_name:
            return True

        base = concat(self.param.filePath,self.get_current_user_base_path())
        src = Path(concat(base,path,name))
        append_name = "" if operator == _OP_COPY else new_name
        dst = Path(concat(base,new_path,append_name))

        if operator == _OP_MOVE:
            shutil.move(src,dst)
        elif operator == _OP_COPY:
            shutil.copy2(src,dst)
        elif operator == _OP_RENAME:
            src.replace(src.parent / new_name)
        else:
            raise ValueError(f"不支持的操作类型:{operator}")
        return True

    # ── ★ 绝对入参族（绝不拼用户根目录）──────────────────────────────

    def get_download_url(self, path_and_name: str) -> str:
        """对应 getDownloadUrl(pathAndName)。★ 绝对入参：入参已含用户根，**不拼**。

        Java（226-231 行）：
            param.domain 非空 → concat(param.domain, encode_ignore_slashes(path_and_name))
            否则              → self.get_proxy_download_url(path_and_name)
        """
        # raise NotImplementedError
        if self.param.domain and self.param.domain.strip():
            return concat(self.param.domain, encode_ignore_slashes(path_and_name))
        # return self.get_download_url(path_and_name)
        return self.get_proxy_download_url(path_and_name)
    

    def get_upload_url(self, path: str, name: str, size: int | None) -> str:
        """对应 getUploadUrl()：一行 —— 转调 self.get_proxy_upload_url(path, name)。"""
        # raise NotImplementedError
        if self.param.domain and self.param.domain.strip():
            return concat(self.param.domain, encode_ignore_slashes(path,name))
        return self.get_proxy_upload_url(path,name)
            

    def _to_file_item(self, file:Path, folder_path: str) -> FileItemResult:
        """对应 fileToFileItem(file, folderPath)。Java 270-284 行。★ 本步的考点。

        规格：
          - type：目录 FOLDER，其余 FILE
          - time：文件的 mtime（Java 是 new Date(lastModified())）
          - size：文件字节数；**目录必须是 None**（Java 是先 set 成 file.length() 再置 null，
            因为文件夹的 length() 是无意义的数字，前端靠 size 空来判断显示 "-"）
          - name：文件名；path：**入参 folder_path 原样**（父目录，不是全路径）
          - 只有 FILE 才 set url，且 url 是这个：
                self.get_download_url(concat(self.get_current_user_base_path(), folder_path, file.getName()))
            ← 这里**必须**自己拼用户根目录！因为本方法是 get_download_url 的**调用方**，
              而 get_download_url 按契约不管拼用户根这件事。这就是"同一个类里两种写法"的那一半。
          - 目录的 url 保持 None

        TODO 写实现
        """
        # raise NotImplementedError
        stat = file.stat()
        is_folder = file.is_dir()

        item = FileItemResult(
            name=file.name,
            time=datetime.fromtimestamp(stat.st_mtime),
            size=None if is_folder else stat.st_size,
            type=FileType.FOLDER if is_folder else FileType.FILE,
            path=folder_path,
        )

        if not is_folder:
            item.url = self.get_download_url(
                concat(self.get_current_user_base_path(),folder_path,file.name)
            )
        return item

    # ── 留到后面的步骤 ──────────────────────────────────────────────

    def upload_file(self, path_and_name: str, input_stream, size: int | None) -> None:
        """对应 uploadFile()。★ 绝对入参。步骤 6 的上传功能才会用到，先留着。

        （Java 里它会 check_path_security，然后 concat(filePath, 用户根, pathAndName) ——
        注意它**拼**了用户根，说明 Java 这边上传的入参其实是相对路径，
        和 getDownloadUrl 的契约不一致。这是 Java 的不一致，★契约以 BaseFileService 注释为准。）
        """
        raise NotImplementedError

    def download_to_stream(self, path_and_name: str , range_header: str | None=None):
        """对应 downloadToStream()（Java 236-267 行）。

        ★ 绝对入参：Java 238 行是 `concat(param.filePath, pathAndName)` —— **没有**用户根。
        这就是步骤 4 埋的伏笔：代理回源是匿名新线程，拼用户根一定拼错。

        7b 用 Starlette 的 FileResponse 快速跑通主链路 —— 它原生支持 Range / 206 /
        Content-Range，底层就是 7c 要手写的东西（先会用，再拆开自己造一遍对照）。

        规格（照 Java 236-267 行，顺序别换）：
          ① check_path_security(path_and_name)
          ② file = Path(concat(self.param.filePath, path_and_name))
             （补 import：`import mimetypes`、`from fastapi.responses import FileResponse`）
          ③ not file.exists() → BizException(ErrorCode.BIZ_FILE_NOT_EXIST)（41004）
          ④ mime 决定 Content-Disposition（Java 246-259）：
               param.proxyLinkForceDownload 为真 → mime = "application/octet-stream"
               否则 → mimetypes.guess_type(file.name)[0] or "application/octet-stream"
                      （对应 Java MediaTypeFactory.getMediaType(...).orElse(OCTET_STREAM)）
               disposition_type = "attachment" if mime == "application/octet-stream" else "inline"
             （★ 判据是 mime 是否等于 octet-stream —— 照抄 Java，别换写成看 proxyLinkForceDownload）
          ⑤ return FileResponse(file, media_type=mime, filename=file.name,
                                content_disposition_type=disposition_type)
             - filename=... 中文名会被 Starlette 编成 filename*=utf-8''...（RFC 5987），
               别自己拼 Content-Disposition 头
             - FileResponse 自动带 Content-Length，并处理 Range → 206

        ⚠️ 已知差异（写进注释）：目录路径会 500（FileResponse 读不了目录）—— Java 同样会炸
        （它只 exists 检查、放过目录），保持一致，不额外加 is_file 判断。
        """
        # raise NotImplementedError
        check_path_security(path_and_name)

        file = Path(concat(self.param.filePath, path_and_name))
        if not file.exists():
            raise BizException(ErrorCode.BIZ_FILE_NOT_EXIST)

        if self.param.proxyLinkForceDownload:
            mime = "application/octet-stream"
        else:
            mime = mimetypes.guess_type(file.name)[0] or "application/octet-stream"

        disposition_type = "attachment" if mime == "application/octet-stream" else "inline"

        # return FileResponse(
        #     file,
        #     media_type=mime,
        #     filename=file.name,
        #     content_disposition_type=disposition_type,
        # )
        return build_file_response(
            file,
            mime=mime,
            disposition_type=disposition_type,
            range_header=range_header
        )

    # 提示：本地存储的"存储源元数据"和"路径安全"分别在
    #   - self.get_storage_source_metadata()
    #   - app/storage/security.py（check_path_security / check_name_security）
    # 别在本地重复实现。
