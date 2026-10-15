"""存储源装配器。对应 Java 的 StorageSourceInitializer。

启动时把 DB 里的存储源逐个变成"活的" service 实例，注册进 registry。
之后整条请求链路只认 registry，不再查 storage_source 表。

Java 的失败模式我们照抄：
  - 单个存储源失败 → log.error 后**继续下一个**（局部失败容忍，一个配错的源不该让整站起不来）
  - 全失败也照常启动 —— 代价是用户访问时才会撞上 50001（错误从启动期推迟到请求期）

时间线提醒：本模块跑在**启动期**，没有 HTTP 请求 → get_current_user_base_path()
走 ADMIN_ID 分支、_get_base_url() 返回 None，都是预期行为。
"""

import logging

from sqlalchemy import func, select

from app.core.db import SessionLocal
from app.models.storage import StorageSource, StorageSourceConfig
from app.storage import registry
from app.storage.base import AbstractBaseFileService
from app.storage.impl.local import LocalServiceImpl
from app.storage.params import LocalParam, ProxyTransferParam

log = logging.getLogger(__name__)

# 存储类型 key → (实现类, 参数类)
#
# Java 靠扫所有 @Service bean + getStorageTypeEnum() 找实现（运行时反射）；
# Python 用一张显式表：IDE 能跳转、静态检查能抓笔误，加新存储类型 = 加一行。
_STORAGE_IMPLS: dict[str, tuple[type[AbstractBaseFileService], type[ProxyTransferParam]]] = {
    "local": (LocalServiceImpl, LocalParam),
}


def build_param(
    param_class: type[ProxyTransferParam],
    configs: list[StorageSourceConfig],
) -> ProxyTransferParam:
    """DB 里的参数行 → Pydantic param 对象。对应 Java StorageSourceContext.getInitParam()。

    用途：启动装配时每个存储源调一次（create_service 的第一步）。storage_source_config
    表里存的是 filePath 这类"死配置行"，service 实例要的是活对象 —— 它就是"DB 行 → param
    对象"的唯一转换点；转不出来（如 filePath 缺失）这个源就不该进注册表。

    Java 那 80 行反射在 Python 侧只剩一句 param_class(**values)，白送的能力：
      - 类型转换："true" → True、"1800" → 1800（Pydantic 宽松模式）
      - 默认值回填：DB 里没存的参数用字段默认值（= Java 的 defaultValue 逻辑）
      - 必填缺失（LocalParam.filePath）→ ValidationError，比 Java 的静默 null 更早暴露

    规格：
      - name 不在 param_class.model_fields 里的行 → log.warning 后**跳过**（对齐 Java 的告警语义）
      - 其余行：values[name] = config.value
      - 最后 return param_class(**values)

    TODO 写实现
    """
    # raise NotImplementedError
    values: dict[str,str|None] = {}
    for config in configs:
        if config.name not in param_class.model_fields:
            log.warning("存储源的配置参数 %s 不在 %s 中, 已忽略", config.name, param_class.__name__)
            continue
        values[config.name] = config.value
    return  param_class(**values)


def create_service(
    row: StorageSource,
    configs: list[StorageSourceConfig],
) -> AbstractBaseFileService:
    """一条 storage_source 记录 → init 好、测过连接的 service 实例。

    用途：启动装配的核心一步 —— 把 DB 里的"死记录"变成能干活的 service 对象，产出交给
    registry 保管，请求期所有链路（文件列表 / 下载 / 配置接口）都从注册表取它。参数装配、
    init、连通性测试三步有一处失败，这条源就进不了注册表（请求期撞 50001，而不是启动失败）。

    规格（顺序别换）：
      ① 按 row.type 查 _STORAGE_IMPLS —— 查不到 = DB 里有、代码里没实现 → 直接抛（KeyError 可以）
      ② param = build_param(param_class, configs)
      ③ service = service_class()
         service.init(name=row.name, storage_id=row.id, storage_key=row.key, param=param)
      ④ service.test_connection()    ← 失败抛 BizException(43011)，由调用方记日志
      ⑤ return service

    TODO 写实现
    """
    # raise NotImplementedError
    assert row.type is not None and row.name is not None and row.key is not None

    impl = _STORAGE_IMPLS.get(row.type)
    if impl is None:
        raise ValueError(f"为实现的存储源类型: {row.type}")
    service_class, param_class = impl
    param = build_param(param_class,configs)
    service = service_class()
    service.init(name=row.name,storage_id=row.id,storage_key=row.key,param=param)
    service.test_connection()
    return service


def load_storage_sources() -> None:
    """对应 StorageSourceInitializer.setApplicationContext() 里那个 for 循环。

    用途：lifespan 启动时调用一次，全站存储源的总装配口。跑完之后 registry 里才有内容，
    /api/storage/list、/api/site/config/storage 才取得到 service —— 它是"启动期一次性装配"
    与"请求期按需取用"两个阶段的衔接点。

    规格：
      ① 取**全部**存储源（不筛 enable —— Java 也不筛：禁用的源照样进注册表，
         过滤是 /api/storage/list 的 SQL 干的）：
             select(StorageSource).order_by(func.ifnull(StorageSource.order_num, -1),
                                            StorageSource.id.desc())
      ② 每条：查它的 configs（按 id 升序）→ create_service → registry.register(row.key, service)
      ③ 单条失败：except Exception → log.error("启动时初始化存储源失败, id=%s, name=%s",
         row.id, row.name, exc_info=True) 后**继续下一条**（不 raise、不 return）
         成功：log.info("启动时初始化存储源成功, ...")（对齐 Java 的两条日志）
      ④ 用 with SessionLocal() as db 包住整段（长生命周期对象只有 service，不是 Session）

    TODO 写实现（现在是空实现，先让应用能启动）
    """
    with SessionLocal() as db:
        rows = db.scalars(
            select(StorageSource).order_by(
                func.ifnull(StorageSource.order_num, -1),
                StorageSource.id.desc(),
            )
        ).all()

        for row in rows:
            try:
                assert row.name is not None and row.key is not None
                configs = db.scalars(
                    select(StorageSourceConfig)
                    .where(StorageSourceConfig.storage_id == row.id)
                    .order_by(StorageSourceConfig.id)
                ).all()

                service = create_service(row, configs)
                registry.register(row.key, service)
                log.info("启动时初始化存储源成功, id: %s, name: %s", row.id, row.name)
            except Exception:
                log.error("启动时初始化存储源失败, id: %s, name: %s", row.id, row.name, exc_info=True)
