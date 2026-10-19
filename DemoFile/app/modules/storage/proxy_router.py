"""服务端代理下载路由。对应 ProxyDownloadController.java（@GetMapping("/pd/{storageKey}/**")）。

    GET /pd/{storage_key}/{file_path}?signature=xxx[&filename=yyy]

匿名链路：<video> 标签与 window.open 无法携带 zfile-token，权限由 URL 中的签名
决定，而不是登录态（设计原因见 app/core/sign.py）。按路径契约，
download_to_stream 属于"绝对入参"族：file_path 已包含用户根（即生成签名时的
字符串），实现中绝不能再拼接 get_current_user_base_path()。

挂载方式：main.py 中 include_router(proxy_router)，不带 /api 前缀（Java 的路径
就是裸 /pd/）。使用同步 def：registry / DB 均为同步调用，交由 FastAPI 线程池执行。
"""

from fastapi import APIRouter, Header

from app.core.db import SessionLocal
from app.core.errors import BizException, ErrorCode
from app.core.path_utils import concat
from app.core.sign import valid_signature_expired
from app.modules.config.service import get_aes_hex_key_or_generate
from app.storage import registry
from app.storage.base import AbstractProxyTransferService

router = APIRouter(tags=["proxy-download"])


@router.get("/pd/{storage_key}/{file_path:path}")
def proxy_download(
    storage_key: str,
    file_path: str,
    signature: str | None = None,
    filename: str | None = None,
    range_header: str|None = Header(default=None, alias="Range"),
):
    """对应 ProxyDownloadController.downAttachment()（Java 47-75 行）。

    执行顺序（与 Java 一致）：
      1. filename 非空时（隐藏文件的 ``?filename=.env`` 形式，见
         get_proxy_download_url 的对应分支）：
           - filename 含 "/" → BIZ_INVALID_FILE_NAME（41022），含分隔符说明这是
             构造路径而非文件名
           - 否则 file_path = concat(file_path, filename)
             （Java 为 filePath + "/" + filename；concat 顺带归一化，效果一致）
         空串 filename（``?filename=``）视同未传（Java isNotEmpty 语义）
      2. registry.get_by_storage_key；结果不是 AbstractProxyTransferService →
         BIZ_UNSUPPORTED_PROXY_DOWNLOAD（41001）。Java 的
         Beans.isInstanceOf(null, ...) 同样为 false，"key 不存在"与"存在但不支持
         代理"合并为同一个 41001。
      3. 使用短会话读取 AES 密钥：with SessionLocal() as db: ...，不要把 Session
         长期持有。
      4. valid_signature_expired(service.storage_id, file_path, signature, hex_key)；
         False → BIZ_INVALID_SIGNATURE（41002）。校验传入原始 file_path（路由值，
         无前导 '/'），校验器内部自行 concat 归一，不要在此提前加工。
      5. 返回 service.download_to_stream(file_path)；返回值直接是 Response，
         FastAPI 原样发出，不包 AjaxJson。

    与 Java 的差异：Java 抛 ErrorPageBizException（/pd/ 属浏览器导航场景，渲染
    HTML 错误页）；这里统一走 BizException → JSON 信封，浏览器标签页会显示 JSON。
    """
    if filename:
        # 含分隔符说明这是构造出来的路径，不是文件名。
        if"/" in filename:
            raise BizException(ErrorCode.BIZ_INVALID_FILE_NAME)
        file_path = concat(file_path,filename)

    service = registry.get_by_storage_key(storage_key)
    if not isinstance(service,AbstractProxyTransferService):
        raise BizException(ErrorCode.BIZ_UNSUPPORTED_PROXY_DOWNLOAD)

    with SessionLocal() as db:
        hex_key = get_aes_hex_key_or_generate(db)

    assert service.storage_id is not None
    if not valid_signature_expired(service.storage_id, file_path, signature, hex_key):
        raise BizException(ErrorCode.BIZ_INVALID_SIGNATURE)
    return service.download_to_stream(file_path,range_header=range_header)
