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
    """当前用户能看到的存储源列表。对应 StorageSourceMapper.xml 的 findUserEnableList。

    用途：/api/storage/list 的核心查询（router.storage_list 唯一调用点）。前端 Header 的
    存储源列表直接由它决定 —— 匿名访客能不能看到源、看到几个、怎么排序，全在这一条 SQL。

    SQL 是照抄 XML 的三表 join，一个条件都别少：
        storage_source ss
        left join user_storage_source uss on ss.id = uss.storage_source_id
        left join user u                   on uss.user_id = u.id
        where  ss.enable   = true
          and  uss.user_id = :user_id
          and  uss.enable  = true
          and  u.enable    = true
        order by ifnull(order_num, -1), ss.id desc

    ★ 四条 where 各自的作用：
        ss.enable     存储源总开关（管理员禁用整个源）
        uss.enable    这个用户能不能看到它（授权行开关）
        u.enable      用户被禁用 → 他名下所有源立刻不可见（别漏了这条，Java 有）
    ★ SQLite 里 Boolean 存 0/1，SQLAlchemy 的 `.is_(True)` 会正确翻译。

    提示：Python 侧用 select(StorageSource) 让它返回完整实体（还要 name/key/type 等 5 个字段），
    不必学 XML 只 select 5 列。

    TODO 写实现
    """
    # raise NotImplementedError
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
    """按 key 查存储源。对应 findByStorageKey。取不到返回 None（抛 50001 是调用方的事）。

    用途：POST /api/site/config/storage 的入口查询 —— 前端带着 URL 第一段（storageKey）
    来要配置，先在这一步把 key 翻译成存储源行；查不到由调用方抛 50001 终结请求。
    """
    # raise NotImplementedError
    return db.scalar(select(StorageSource).where(StorageSource.key == storage_key))


def get_user_storage_source(db: Session, user_id: int, storage_id: int) -> UserStorageSource | None:
    """取 (user_id, storage_id) 的授权行。对应 getByUserIdAndStorageId。没有返回 None。

    用途：storage_config 组装响应时调它，拿到的那行同时喂两处 —— permissions 给
    build_permission_map（能干什么）、root_path 给响应体 rootPath（能看哪个子目录）。
    "没有授权行"是正常分支（权限全 False + rootPath 兜底 "/"），不是错误。
    """
    # raise NotImplementedError
    return db.scalar(
              select(UserStorageSource).where(
                  UserStorageSource.user_id == user_id,
                  UserStorageSource.storage_source_id == storage_id,
              )
          )
      


def build_permission_map(uss: UserStorageSource | None) -> dict[str, bool]:
    """当前用户在该存储源的权限表 {操作名: 有没有}。

    用途：storage_config 响应里 permission 字段的组装函数。前端拿它决定每个按钮/菜单项的
    显隐 —— "后端算权限、前端只读结果"的分工就落在这里。

    对应 UserStorageSourceService.buildPermissionMap()。★ 三个要点：
      - 遍历 FileOperatorType 的**全部** 19 个值（包括没权限的，显式置 False）。
        前端 storage-config.ts 直接读 originPermission.xxx —— key 缺失 = undefined，
        按钮显隐/上下文菜单逻辑当场抽风。所以绝不能写成"只放有权限的"
      - permissions 是逗号分隔字符串（Java 是 Set<String> + TypeHandler），
        比较时先 split(",")；包含判定用集合（permissions_set = set(...)）
      - uss is None 或 permissions 为空 → 全部 False

    TODO 写实现
    """
    # raise NotImplementedError
    stored: set[str] = set()
    if uss is not None and uss.permissions:
        stored = {p for p in uss.permissions.split(",") if p}
    return {op.value: op.value in stored for op in FileOperatorType}


def has_user_storage_operator_permission(
    db: Session, user_id: int | None, storage_id: int, operator: FileOperatorType
) -> bool:
    """对应 hasUserStorageOperatorPermission。指定用户在指定存储源有没有某个操作权限。

    用途：责任链最后一道（FileDownloadPermissionCommand）调它两次（DOWNLOAD /
    PREVIEW）—— 两个都没有就把响应里所有 url 置 None（"没有下载也没有预览" = 不给下载地址）。

    规格（照 Java UserStorageSourceService:78-87）：
      - user_id 为 None → 用**当前请求用户**：context.get_current_user_id() or ANONYMOUS_ID
        （Java 是 hasCurrentUserStorageOperatorPermission；普通模式下 FileContext.
        operator_user_id 就是 None，所以这是主路径，不是兜底分支）
      - 复用 get_user_storage_source(db, user_id, storage_id)；行不存在 或 permissions
        为空 → False
      - 否则 permissions 按 ',' split 成集合，判断 operator.value 是否在里面
        （build_permission_map 算全部 19 个；这里只要一个 —— 别为了单值检查去绕大圈）

    TODO 写实现
    """
    # raise NotImplementedError
    if user_id is None:
        user_id = context.get_current_user_id() or ANONYMOUS_ID

    uss = get_user_storage_source(db,user_id,storage_id)
    if uss is None or not uss.permissions:
        return False
    return operator.value in {p for p in uss.permissions.split(",") if p}
