"""本地文件系统存储实现，对应 LocalServiceImpl.java。

相对入参族的方法（file_list / get_file_item / new_folder / delete_* / rename_* /
copy_* / move_*）在内部拼接 param.filePath 与当前用户根目录；get_download_url /
download_to_stream 属于绝对入参族，入参已包含用户根，不能再拼。

路径与文件名校验统一走 app/storage/security.py，存储源能力由
get_storage_source_metadata 声明。
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
    """对应 LocalServiceImpl.java。

    Java 的 @Service + @Scope(PROTOTYPE) 对应 loader 的装配方式：每个存储源在
    启动时实例化一次本类。
    """

    def _init(self) -> None:
        """对应 LocalServiceImpl.init()：校验 param.filePath 存在。

        报错信息与 Java 保持一致，运维依赖该字符串定位配置问题。
        """
        file_path = Path(self.param.filePath)
        if not file_path.exists():
            raise BizException(ErrorCode.BIZ_STORAGE_INIT_ERROR,f"文件路径: 「{file_path.resolve()}」不存在,请检查填写是否正确.")
        

    def get_storage_type(self) -> StorageType:
        """对应 getStorageTypeEnum()。"""
        return StorageType.LOCAL

    def get_storage_source_metadata(self) -> StorageSourceMetadata:
        """对应 getStorageSourceMetadata()：只覆盖与默认值不同的两项。

        uploadType = PROXY，needCreateFolderBeforeUpload = false；其余布尔字段
        保持 StorageSourceMetadata 的默认值。
        """
        return StorageSourceMetadata(
            uploadType=UploadType.PROXY,
            needCreateFolderBeforeUpload=False,
        )

    # ── 相对入参族（内部要拼用户根目录）────────────────────────────────

    def file_list(self, folder_path: str) -> list[FileItemResult]:
        """对应 fileList(folderPath)。

        路径先做安全检查，再与用户根目录拼接。目标不是已存在的目录时抛
        BIZ_FOLDER_NOT_EXIST。目录为空时返回空列表（Java listFiles() 返回 null
        时同样转为空列表）。_to_file_item 接收的 folder_path 是父目录原值。
        """
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

        与 file_list 的差异：不存在时返回 None 而不是抛异常；_to_file_item 的
        folder_path 取 get_parent_path(path_and_name)。
        """
        check_path_security(path_and_name)

        full_path = concat(self.param.filePath, self.get_current_user_base_path(), path_and_name)
        file = Path(full_path)
        if not file.exists():
            return None
        return self._to_file_item(file, get_parent_path(path_and_name))
        
    def new_folder(self, path: str, name: str) -> bool:
        """对应 newFolder(path, name)：校验 → 拼接 → mkdir。

        mkdir 使用 parents=True，保持 hutool FileUtil.mkdir 递归创建父目录的语义。
        """
        check_path_security(path)
        check_name_security(name)

        folder = Path(concat(self.param.filePath, self.get_current_user_base_path(), path, name))
        folder.mkdir(parents=True, exist_ok=True)
        return folder.is_dir()


    def delete_file(self, path: str, name: str) -> bool:
        """对应 deleteFile(path, name)：校验 → 拼接 → 删除。

        文件与目录共用此逻辑，目录走 shutil.rmtree，以支持删除非空文件夹。
        目标不存在时返回 True，与 hutool 的语义一致。
        """
        check_path_security(path)
        check_name_security(name)
        target = Path(concat(self.param.filePath, self.get_current_user_base_path(), path, name))
        if not target.exists():
            return True # 与hutool保持一致
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
        return not target.exists()


    def delete_folder(self, path: str, name: str) -> bool:
        """对应 deleteFolder()：删除逻辑与 delete_file 一致。

        保留独立方法以对应 Java 的接口形状。
        """
        check_path_security(path)
        check_name_security(name)
        target = Path(concat(self.param.filePath, self.get_current_user_base_path(), path, name))
        if not target.exists():
            return True # 与hutool保持一致
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
        return not target.exists()


    def rename_file(self, path: str, name: str, new_name: str) -> bool:
        """对应 renameFile()：_operate_file(..., RENAME)。"""
        return self._operate_file(path,name,path,new_name,_OP_RENAME)

    def rename_folder(self, path: str, name: str, new_name: str) -> bool:
        """对应 renameFolder()，与 rename_file 走同一实现。"""
        return self._operate_file(path,name,path,new_name,_OP_RENAME)

    def copy_file(self, path: str, name: str, target_path: str, target_name: str) -> bool:
        """对应 copyFile()：_operate_file(..., COPY)。"""
        return self._operate_file(path,name,target_path,target_name,_OP_COPY)

    def copy_folder(self, path: str, name: str, target_path: str, target_name: str) -> bool:
        """对应 copyFolder()，与 copy_file 走同一实现。"""
        return self._operate_file(path,name,target_path,target_name,_OP_COPY)

    def move_file(self, path: str, name: str, target_path: str, target_name: str) -> bool:
        """对应 moveFile()：_operate_file(..., MOVE)。"""
        return self._operate_file(path,name,target_path,target_name,_OP_MOVE)


    def move_folder(self, path: str, name: str, target_path: str, target_name: str) -> bool:
        """对应 moveFolder()，与 move_file 走同一实现。"""
        return self._operate_file(path,name,target_path,target_name,_OP_MOVE)

    def _operate_file(self, path: str, name: str, new_path: str, new_name: str, operator: str) -> bool:
        """对应 operateFile()，四种操作共用的核心。

        先校验路径与文件名。原路径与目标完全相同（path == new_path 且
        name == new_name）时直接返回 True，避免部分协议下"重命名自身"的报错。
        src 是源完整路径；dst 在 COPY 时是目标目录（保留原名），在 MOVE / RENAME
        时是完整新路径。

        MOVE / COPY 分别使用 shutil.move / shutil.copy2，RENAME 使用 Path.replace。
        与 Java 的差异：hutool 的 FileUtil 失败时返回 false，shutil 失败时抛异常；
        这里让异常冒泡到全局处理器，前端能拿到明确错误。
        """
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

    # ── 绝对入参族（入参已含用户根，不再拼接）────────────────────────

    def get_download_url(self, path_and_name: str) -> str:
        """对应 getDownloadUrl(pathAndName)。入参已含用户根，不再拼接。

        配置了 param.domain 时直接用它拼地址，否则交给代理下载 URL。
        """
        if self.param.domain and self.param.domain.strip():
            return concat(self.param.domain, encode_ignore_slashes(path_and_name))
        return self.get_proxy_download_url(path_and_name)


    def get_upload_url(self, path: str, name: str, size: int | None) -> str:
        """对应 getUploadUrl()：配置了 param.domain 时直接拼地址，否则走代理上传 URL。"""
        if self.param.domain and self.param.domain.strip():
            return concat(self.param.domain, encode_ignore_slashes(path,name))
        return self.get_proxy_upload_url(path,name)
            

    def _to_file_item(self, file:Path, folder_path: str) -> FileItemResult:
        """对应 fileToFileItem(file, folderPath)。

        type 由是否目录决定，time 取 mtime。size 仅文件有值，目录为 None（前端
        据此显示 "-"）。path 保存父目录 folder_path 原值。只有文件生成 url；
        本方法是 get_download_url 的调用方，必须自行拼接用户根目录。
        """
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

    # ── 上传与代理下载 ──────────────────────────────────────────────

    def upload_file(self, path_and_name: str, input_stream, size: int | None) -> None:
        """对应 uploadFile()。当前未实现，上传功能接入时补齐。

        Java 的实现会拼接用户根目录，其上传入参实际是相对路径，与
        getDownloadUrl 的绝对路径契约不一致；补齐时以 BaseFileService 的
        绝对入参契约为准。
        """
        raise NotImplementedError

    def download_to_stream(self, path_and_name: str , range_header: str | None=None):
        """对应 downloadToStream()，通过 build_file_response 输出支持 Range 的响应。

        绝对入参：path_and_name 已含用户根，这里只拼 param.filePath。代理回源
        运行在匿名线程中，再拼用户根会取到错误的目录。

        proxyLinkForceDownload 为真时统一使用 application/octet-stream，否则按
        扩展名猜测，失败时回落到 octet-stream。Content-Disposition 的类型取决于
        最终 mime 是否为 octet-stream，与 Java 的判据一致；中文文件名按 RFC 5987
        编码。

        已知差异：目录路径会因读取失败返回 500。Java 同样只做 exists 检查，
        这里保持一致，不额外加 is_file 判断。
        """
        check_path_security(path_and_name)

        file = Path(concat(self.param.filePath, path_and_name))
        if not file.exists():
            raise BizException(ErrorCode.BIZ_FILE_NOT_EXIST)

        if self.param.proxyLinkForceDownload:
            mime = "application/octet-stream"
        else:
            mime = mimetypes.guess_type(file.name)[0] or "application/octet-stream"

        disposition_type = "attachment" if mime == "application/octet-stream" else "inline"

        return build_file_response(
            file,
            mime=mime,
            disposition_type=disposition_type,
            range_header=range_header
        )
