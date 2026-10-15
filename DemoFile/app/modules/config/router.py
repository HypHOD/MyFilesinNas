from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.auth import get_current_user_id
from app.core.db import get_db
from app.core.errors import BizException, ErrorCode
from app.core.response import AjaxJson, success_data
from app.models.user import ANONYMOUS_ID
from app.modules.config.schemas import FileListConfigRequest, FrontSiteConfigResult
from app.modules.config.service import get_site_config
from app.modules.storage.service import (
    build_permission_map,
    find_by_storage_key,
    get_user_storage_source,
)
from app.storage import registry
from app.storage.schemas import StorageSourceConfigResult

router = APIRouter(prefix="/site", tags=["site"])


@router.get("/config/global")
def global_config(db: Session = Depends(get_db),user_id:int = Depends(get_current_user_id)) -> AjaxJson[FrontSiteConfigResult]:
    """GET /api/site/config/global

    对应 SiteController.globalConfig()。注意 Java 那边**永远返回成功**，
    不检查 installed —— 系统没安装也要把配置发出去，前端靠 installed 字段决定跳不跳安装页。
    """
    config = get_site_config(db)

    # 白名单取自响应模型本身：username/password/guestIndexHtml 不在里面，永远进不来。
    # debugMode / guest 也不在 SiteConfig 里，靠 FrontSiteConfigResult 的默认值。
    allowed = set(FrontSiteConfigResult.model_fields)
    result = FrontSiteConfigResult(**config.model_dump(include=allowed))
    result.guest = user_id == ANONYMOUS_ID and bool((config.guestIndexHtml or "").strip())
    # return success_data(FrontSiteConfigResult(**config.model_dump(include=allowed)))
    return success_data(result)


@router.post("/config/storage")
def storage_config(
    request: FileListConfigRequest,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> AjaxJson[StorageSourceConfigResult]:
    """对应 SiteController.storageList() → StorageSourceService.getStorageConfigSource()。

    用途：前端进任意存储源/目录前必调（useFileData.js）—— 响应里的 permission / metadata /
    rootPath 被 updateFolderConfig 存进前端 store，之后所有按钮显隐、上传方式、根目录显示
    都读它。所以 permission 和 metadata **必须永远有值**。

    规格（照 Java 的顺序）：
      ① storage_source = find_by_storage_key(db, request.storageKey)
         取不到 → raise BizException(ErrorCode.INVALID_STORAGE_SOURCE)（50001）
      ② service = registry.get_by_storage_id(storage_source.id)
         ★ 用 id 版不是 key 版：启动时初始化失败的源不在注册表里，在这一步暴露成 50001
      ③ 密码校验：password_config 表还没做 → 恒 passed，留 TODO 注释。
         Java 在此处会算 fullPath = concat(service.get_current_user_base_path(), request.path)
         供密码校验用；我们连密码都没做，先不拼 —— 等做文件夹密码那步把这条线索接回来
         （别把 get_current_user_base_path() 的调用忘了，它是"用户根目录"的活样例）
      ④ readme：readme_config 表还没做 → readmeText / readmeDisplayMode 恒 None（字段必须在）
      ⑤ uss = get_user_storage_source(db, user_id, storage_source.id)
      ⑥ permission = build_permission_map(uss)
      ⑦ metadata = service.get_storage_source_metadata()      ← ★ 永远要有
      ⑧ rootPath = uss.root_path if uss is not None else "/"
      ⑨ return success_data(StorageSourceConfigResult(...))

    ★ 差异注释（写进代码里）：Java **不检查**当前用户对该源有没有权限 ——
      没授权行也返回 200，permission 全 False，前端据此隐藏所有按钮。
      我们照抄这个行为；真正的隔离在步骤 6 的文件列表接口。

    TODO 写实现
    """
    # raise NotImplementedError
    storage_source = find_by_storage_key(db, request.storageKey)
    if storage_source is None:
        raise BizException(ErrorCode.INVALID_STORAGE_SOURCE)

    service = registry.get_by_storage_id(storage_source.id)
    uss = get_user_storage_source(db,user_id,storage_source.id)
    return success_data(
        StorageSourceConfigResult(
            readmeText=None,
            readmeDisplayMode=None,
            defaultSwitchToImgMode=storage_source.default_switch_to_img_mode,
            permission=build_permission_map(uss),
            metadata=service.get_storage_source_metadata(),   # ← 永远要有
            rootPath=uss.root_path if uss is not None else "/",
        )
    )


@router.get("/config/userRootPath/{storage_key}")
def user_root_path(storage_key: str) -> AjaxJson[str]:
    """对应 SiteController.getUserRootPath()。

    用途：前端单独查"我在这个存储源里的根目录"。同时它是 registry.get_by_storage_key
    "取不到返回 None 不抛异常"语义的样板场景：URL 第一段可能根本不是存储源 key，
    这种情况返回 "" 让前端静默处理，而不是 50001。

    规格：
      - service = registry.get_by_storage_key(storage_key)
        ★ 用 key 版（取不到返回 None 不是异常）—— 这个端点正是 get_by_storage_key
           "不抛异常"语义的存在理由
      - service 为 None → 返回 ""
      - 否则返回 service.get_current_user_base_path()（它兜底 "/"，永不返回 None）

    注意本端点没有 user_id 依赖：当前用户是中间件写进 contextvar 的，
    get_current_user_base_path() 内部自己去取 —— 和 Java 用 ThreadLocal 的方式同构。

    TODO 写实现
    """
    # raise NotImplementedError
    service = registry.get_by_storage_key(storage_key)
    if service is None:
        return success_data("")
    return success_data(service.get_current_user_base_path())
