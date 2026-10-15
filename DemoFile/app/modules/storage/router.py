"""文件列表相关路由。对应 FileController。

    GET  /api/storage/list    存储源列表（步骤 5）
    POST /api/storage/files   文件列表 + 责任链（步骤 6）
"""

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.auth import get_current_user_id
from app.core.db import get_db
from app.core.errors import BizException, ErrorCode
from app.core.response import AjaxJson, success_data
from app.modules.storage.schemas import FileListRequest
from app.modules.storage.service import find_by_storage_key, find_user_enable_list
from app.storage import registry
from app.storage.chain import FileContext, execute_file_chain
from app.storage.enums import StorageType
from app.storage.schemas import FileInfoResult, StorageSourceResult, StorageTypeInfo

log = logging.getLogger(__name__)

router = APIRouter(prefix="/storage", tags=["storage"])


@router.get("/list")
def storage_list(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> AjaxJson[list[StorageSourceResult]]:
    """对应 FileController.storageList()。注意返回的是 getSuccessData（普通 data），
    不是分页 —— 所以**没有 dataCount**。

    用途：前端 Header 的存储源列表接口 —— 页面启动后紧跟全局配置被调，决定页面上列出哪些源。

    组装规格（对应 StorageSourceConvert.entityToResultList）：
      - name / key / searchEnable / defaultSwitchToImgMode 从实体直接搬
      - type 转成**对象**：StorageTypeInfo(key=r.type, description=StorageType(r.type).description)
        ⚠️ DB 里可能出现代码还没实现的类型（StorageType(r.type) 抛 ValueError）→
           那一条 try 掉 + log.warning，别让整个列表 500（Java 侧枚举反序列化失败也是会炸的，
           我们做得比它稳一点，把差异写进注释）
      - rows = find_user_enable_list(db, user_id)，返回 success_data([...])

    匿名也能调：未登录时 user_id 兜底成 2(guest)，能不能看到源由 guest 的授权行决定 ——
    这正是 seed 脚本必须给 guest 插行的原因。

    TODO 写实现
    """
    # raise NotImplementedError
    rows = find_user_enable_list(db,user_id)
    results: list[StorageSourceResult] = []
    for row in rows:
        try:
            storage_type = StorageType(row.type or "")
        except ValueError:
          # db有代码没实现的类型: 跳过
          log.warning("存储源类型未实现, 已跳过: id=%s, type=%s",row.id,row.type)
          continue
        results.append(
            StorageSourceResult(
                name=row.name,
                key=row.key,
                type=StorageTypeInfo(key = storage_type.value,description=storage_type.description),
                searchEnable=row.search_enable,
                defaultSwitchToImgMode=row.default_switch_to_img_mode,
            )
        )
    return success_data(results)


@router.post("/files")
def file_list(
    request: FileListRequest,
    db: Session = Depends(get_db),
) -> AjaxJson[FileInfoResult]:
    """POST /api/storage/files —— 前端"打开目录"的主接口（useFileData.js:97 唯一调用点）。

    用途：文件列表主链路。响应 data.files 直接渲染表格、data.passwordPattern 存密码态
    （现在恒 null）；没有它前端进任何目录都是空白页（就是步骤 5 末尾你看到的现象）。
    请求里的排序参数由链里的 FileSortCommand 消费。

    规格（照 FileController.list，71-95 行）：
      ① storage_source = find_by_storage_key(db, request.storageKey)
         取不到 → BizException(ErrorCode.INVALID_STORAGE_SOURCE)（50001）
      ② request.handle_default_value()   ← 必须先补默认值：之后 path 必以 '/' 开头
      ③ service = registry.get_by_storage_id(storage_source.id)
         （初始化失败的源在这一步暴露 50001 —— 和 storage_config 同一个语义）
      ④ file_item_list = service.file_list(request.path)
         ★ path 是相对用户根的路径，拼用户根是 service 内部的事（相对入参族）
      ⑤ ctx = FileContext(storage_id=..., file_list_request=request,
                          file_item_list=..., file_service=service)
         execute_file_chain(ctx)
         （operator_user_id 不传：普通模式 None，权限命令内部回退到当前登录用户 —— 与 Java 一致）
      ⑥ return success_data(FileInfoResult(files=ctx.file_item_list,
                                           passwordPattern=ctx.password_pattern))

    TODO 写实现
    """
    # raise NotImplementedError
    storage_source = find_by_storage_key(db,request.storageKey)
    if storage_source is None:
        raise BizException(ErrorCode.INVALID_STORAGE_SOURCE)
    request.handle_default_value()

    service = registry.get_by_storage_id(storage_source.id)
    file_item_list = service.file_list(request.path)

    ctx = FileContext(
        storage_id=storage_source.id,
        file_list_request=request,
        file_item_list=file_item_list,
        file_service=service,
    )

    execute_file_chain(ctx)

    return success_data(
        FileInfoResult(
            files=ctx.file_item_list,
            passwordPattern=ctx.password_pattern
        )
    )

