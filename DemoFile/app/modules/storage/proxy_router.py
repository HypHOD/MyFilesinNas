"""服务端代理下载路由。对应 ProxyDownloadController.java（@GetMapping("/pd/{storageKey}/**")）。

    GET /pd/{storage_key}/{file_path}?signature=xxx[&filename=yyy]

这条路由是**匿名链路**：`<video>` 标签和 window.open 都带不了 zfile-token，所以权限不由
"你是谁"决定，而由 URL 里的签名决定（为什么这么设计，翻 app/core/sign.py 的模块注释）。
按路径契约，download_to_stream 是**绝对入参族** —— file_path 已含用户根（它就是当初生成
签名时的那个字符串），实现里**绝不**再拼 get_current_user_base_path()。

挂载方式：main.py 里 include_router(proxy_router) —— **不带 /api 前缀**（Java 的路径
就是裸的 /pd/，不是 /api/pd/）。同步 def：registry / DB 全是同步调用，让 FastAPI
丢线程池执行，别写 async（跟 modules/storage/router.py 一个风格）。
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

    规格（照 Java，顺序别换）：
      ① filename 非空时（隐藏文件的 `?filename=.env` 形式，见 get_proxy_download_url 的 ①）：
           - filename 含 "/" → BizException(ErrorCode.BIZ_INVALID_FILE_NAME)（41022）
             ——含分隔符说明是构造出来的路径，不是文件名
           - 否则 file_path = concat(file_path, filename)
             （Java 是 filePath + "/" + filename；我们用 concat 顺带归一化，效果一致）
         空串 filename（`?filename=`）当作没传 —— Java isNotEmpty 语义
      ② service = registry.get_by_storage_key(storage_key)
         not isinstance(service, AbstractProxyTransferService) → BizException(
             ErrorCode.BIZ_UNSUPPORTED_PROXY_DOWNLOAD)（41001）
         ★ Java 是 Beans.isInstanceOf(null, ...) == false —— "key 没找到"和"找到了但
           不支持代理"落进**同一个** 41001，照抄这个合并
      ③ with SessionLocal() as db: hex_key = get_aes_hex_key_or_generate(db)
         （短会话，和 _lookup_user_root_path 一样的纪律 —— 别把 Session 存下来）
      ④ assert service.storage_id is not None（init 过必非空）
         valid_signature_expired(service.storage_id, file_path, signature, hex_key)
         为 False → BizException(ErrorCode.BIZ_INVALID_SIGNATURE)（41002）
         ★ 校验用**原始 file_path**（路由给的、无前导 '/'）—— 校验器内部自己 concat 归一，
           别在这里先加工
      ⑤ return service.download_to_stream(file_path)   ← 返回值直接是 Response 对象，
         FastAPI 原样发出（不用包 AjaxJson）

    差异（写进注释）：Java 抛 ErrorPageBizException（/pd/ 是浏览器导航场景，渲染 HTML
    错误页），我们统一走 BizException → JSON 信封 —— 浏览器标签页会显示 JSON，教学项目
    可接受。

    TODO 写实现
    """
    # raise NotImplementedError
    if filename:
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
