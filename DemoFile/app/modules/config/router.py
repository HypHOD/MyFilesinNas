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

    对应 SiteController.globalConfig()。Java 始终返回成功，不检查 installed；
    系统未安装时也返回配置，前端根据 installed 字段决定是否跳转安装页。
    """
    config = get_site_config(db)

    # 白名单取自响应模型本身：username/password/guestIndexHtml 不在其中，不会外泄。
    # debugMode / guest 也不在 SiteConfig 中，使用 FrontSiteConfigResult 的默认值。
    allowed = set(FrontSiteConfigResult.model_fields)
    result = FrontSiteConfigResult(**config.model_dump(include=allowed))
    result.guest = user_id == ANONYMOUS_ID and bool((config.guestIndexHtml or "").strip())
    return success_data(result)


@router.post("/config/storage")
def storage_config(
    request: FileListConfigRequest,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> AjaxJson[StorageSourceConfigResult]:
    """对应 SiteController.storageList() → StorageSourceService.getStorageConfigSource()。

    前端进入任意存储源/目录前必调（useFileData.js）。响应中的 permission / metadata /
    rootPath 由 updateFolderConfig 写入前端 store，后续按钮显隐、上传方式和根目录
    显示都依赖它，因此 permission 与 metadata 必须始终有值。

    执行顺序（与 Java 一致）：
      1. find_by_storage_key；取不到抛 INVALID_STORAGE_SOURCE（50001）
      2. registry.get_by_storage_id：使用 id 版而非 key 版，使启动时初始化失败的源
         在这一步暴露为 50001
      3. 密码校验：password_config 表尚未实现，当前恒为 passed。Java 在此会计算
         fullPath = concat(service.get_current_user_base_path(), request.path) 供密码
         校验使用；实现文件夹密码时需接回这条线索
      4. readme：readme_config 表尚未实现，readmeText / readmeDisplayMode 恒为 None
         （字段必须存在）
      5. uss = get_user_storage_source(db, user_id, storage_source.id)
      6. permission = build_permission_map(uss)
      7. metadata = service.get_storage_source_metadata()，必须始终有值
      8. rootPath = uss.root_path if uss is not None else "/"

    Java 不检查当前用户对该源是否有权限：没有授权行也返回 200，permission 全为
    False，前端据此隐藏所有按钮。这里保持相同行为；真正的隔离在文件列表接口。
    """
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
            metadata=service.get_storage_source_metadata(),   # metadata 必须始终有值。
            rootPath=uss.root_path if uss is not None else "/",
        )
    )


@router.get("/config/userRootPath/{storage_key}")
def user_root_path(storage_key: str) -> AjaxJson[str]:
    """对应 SiteController.getUserRootPath()。

    前端单独查询"我在这个存储源里的根目录"。URL 第一段可能不是任何存储源 key，
    此时返回 "" 让前端静默处理，而不是 50001。这也是 registry.get_by_storage_key
    选择"取不到返回 None 而非抛异常"的场景。

    key 不存在时返回 ""；否则返回 service.get_current_user_base_path()（内部兜底
    "/"，永不返回 None）。

    本端点没有 user_id 依赖：当前用户由中间件写入 contextvar，
    get_current_user_base_path() 内部自行读取，与 Java 使用 ThreadLocal 的方式一致。
    """
    service = registry.get_by_storage_key(storage_key)
    if service is None:
        return success_data("")
    return success_data(service.get_current_user_base_path())
