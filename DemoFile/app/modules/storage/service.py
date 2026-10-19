"""存储源 / 用户授权的查询层。

对应 Java 的 StorageSourceService + UserStorageSourceService（只搬查询部分，
不含后台管理的增删改和缓存）。职责边界：router 只做参数校验和响应组装，SQL 一律在这里。
"""

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.core import context
from app.models.storage import StorageSource, UserStorageSource
from app.models.user import ANONYMOUS_ID, User
from app.storage.enums import FileOperatorType


def find_user_enable_list(db: Session, user_id: int) -> list[StorageSource]:
    """当前用户可见的存储源列表，对应 StorageSourceMapper.xml 的 findUserEnableList。

    /api/storage/list 的核心查询。三表 join 和四个过滤条件缺一不可：

        ss.enable     存储源总开关
        uss.user_id   当前用户
        uss.enable    该用户的授权开关
        u.enable      用户未被禁用（禁用后其名下所有源立即不可见）

    排序为 ifnull(order_num, -1) 后按 id 倒序。SQLite 中布尔值存为 0/1，
    SQLAlchemy 的 .is_(True) 会正确翻译。
    """
    return list(
        db.scalars(
            select(StorageSource)
            .join(UserStorageSource, StorageSource.id == UserStorageSource.storage_source_id)
            .join(User, UserStorageSource.user_id == User.id)
            .where(
                StorageSource.enable.is_(True),
                UserStorageSource.user_id == user_id,
                UserStorageSource.enable.is_(True),
                User.enable.is_(True),
            )
            .order_by(func.ifnull(StorageSource.order_num, -1), StorageSource.id.desc())
        ).all()
    )


def find_by_storage_key(db: Session, storage_key: str) -> StorageSource | None:
    """按 key 查询存储源，对应 findByStorageKey。

    取不到返回 None，是否抛 50001 由调用方决定。
    """
    return db.scalar(select(StorageSource).where(StorageSource.key == storage_key))


def get_user_storage_source(db: Session, user_id: int, storage_id: int) -> UserStorageSource | None:
    """取 (user_id, storage_id) 的授权行，对应 getByUserIdAndStorageId。

    没有授权行返回 None，属于正常分支（权限全部为 False、rootPath 兜底 "/"）。
    """
    return db.scalar(
              select(UserStorageSource).where(
                  UserStorageSource.user_id == user_id,
                  UserStorageSource.storage_source_id == storage_id,
              )
          )
      


def build_permission_map(uss: UserStorageSource | None) -> dict[str, bool]:
    """当前用户在该存储源的权限表 {操作名: 是否授权}。

    对应 UserStorageSourceService.buildPermissionMap()。遍历 FileOperatorType
    全部 19 个值并显式给出布尔值：前端 storage-config.ts 直接读取
    originPermission.xxx，缺少 key 会得到 undefined，导致按钮显隐逻辑异常。

    permissions 是逗号分隔字符串（Java 侧为 Set<String> + TypeHandler），
    先 split 成集合再判断。uss 为 None 或 permissions 为空时全部为 False。
    """
    stored: set[str] = set()
    if uss is not None and uss.permissions:
        stored = {p for p in uss.permissions.split(",") if p}
    return {op.value: op.value in stored for op in FileOperatorType}


def has_user_storage_operator_permission(
    db: Session, user_id: int | None, storage_id: int, operator: FileOperatorType
) -> bool:
    """对应 hasUserStorageOperatorPermission：指定用户在指定存储源是否拥有某个操作权限。

    责任链的下载权限命令调用它两次（DOWNLOAD / PREVIEW）。user_id 为 None 时回退
    到当前请求用户（context 为空则用匿名用户），这是普通模式下的主路径。

    复用 get_user_storage_source 查询；行不存在或 permissions 为空时返回 False。
    """
    if user_id is None:
        user_id = context.get_current_user_id() or ANONYMOUS_ID

    uss = get_user_storage_source(db,user_id,storage_id)
    if uss is None or not uss.permissions:
        return False
    return operator.value in {p for p in uss.permissions.split(",") if p}
