"""文件列表相关路由。对应 FileController。

    GET  /api/storage/list    存储源列表
    POST /api/storage/files   文件列表 + 责任链
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
    """对应 FileController.storageList()。返回 getSuccessData 的普通 data，不是分页，
    因此没有 dataCount。

    前端 Header 的存储源列表接口：页面启动后紧跟全局配置调用，决定页面列出哪些源。

    组装规则（对应 StorageSourceConvert.entityToResultList）：
      - name / key / searchEnable / defaultSwitchToImgMode 直接取自实体
      - type 转成对象 StorageTypeInfo(key=..., description=...)
        数据库中可能出现尚未实现的类型，StorageType(r.type) 会抛 ValueError；该条
        跳过并记录 warning，避免整个列表返回 500。
      - rows = find_user_enable_list(db, user_id)

    匿名用户同样可调用：未登录时 user_id 兜底为 2（guest），可见性由 guest 的授权行
    决定，这也是 seed 脚本必须为 guest 插入授权行的原因。
    """
    rows = find_user_enable_list(db,user_id)
    results: list[StorageSourceResult] = []
    for row in rows:
        try:
            storage_type = StorageType(row.type or "")
        except ValueError:
          # 数据库中存在尚未实现的类型，跳过该条。
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
    """POST /api/storage/files —— 前端打开目录的主接口（useFileData.js:97 唯一调用点）。

    文件列表主链路。响应 data.files 用于渲染表格，data.passwordPattern 保存密码态
    （当前恒为 null）；缺少该接口时前端进入任何目录都是空白页。请求中的排序参数由
    责任链中的 FileSortCommand 消费。

    执行顺序（对应 FileController.list，71-95 行）：
      1. find_by_storage_key；取不到抛 INVALID_STORAGE_SOURCE（50001）
      2. request.handle_default_value()：必须先补默认值，之后 path 保证以 '/' 开头
      3. registry.get_by_storage_id：初始化失败的源在这一步暴露为 50001，与
         storage_config 语义一致
      4. service.file_list(request.path)：path 是相对用户根的路径，拼接用户根由
         service 内部完成（相对入参族）
      5. 构造 FileContext 并执行 execute_file_chain；operator_user_id 不传（普通模式
         为 None，权限命令内部回退到当前登录用户，与 Java 一致）
      6. 返回 FileInfoResult(files=ctx.file_item_list, passwordPattern=...)
    """
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

