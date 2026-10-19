"""存储源装配器，对应 Java 的 StorageSourceInitializer。

启动时把数据库中的存储源逐条初始化为 service 实例并注册进 registry，之后请求
链路只从 registry 取用。本模块运行在启动期，没有 HTTP 请求上下文：
get_current_user_base_path() 走 ADMIN_ID 分支、_get_base_url() 返回 None，
均为预期行为。
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
# Java 通过扫描 @Service bean 和 getStorageTypeEnum() 在运行时发现实现；
# Python 使用显式映射表：IDE 可跳转、静态检查能发现笔误，新增类型只需加一行。
_STORAGE_IMPLS: dict[str, tuple[type[AbstractBaseFileService], type[ProxyTransferParam]]] = {
    "local": (LocalServiceImpl, LocalParam),
}


def build_param(
    param_class: type[ProxyTransferParam],
    configs: list[StorageSourceConfig],
) -> ProxyTransferParam:
    """将 DB 参数行转换为 Pydantic param 对象，对应 Java StorageSourceContext.getInitParam()。

    启动装配时每个存储源调用一次。storage_source_config 存的是 filePath 这类静态
    配置行，service 需要活对象，这里是两者之间唯一的转换点；转换失败（如 filePath
    缺失）的存储源不会进入注册表。

    Java 的反射逻辑在这里简化为 param_class(**values)：Pydantic 负责类型转换、
    默认值回填和必填校验。

    不在 model_fields 中的配置行记录 warning 后跳过，与 Java 的告警语义一致。
    """
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
    """将一条 storage_source 记录转换为初始化完成、连接测试通过的 service 实例。

    参数装配、init、连通性测试任一步失败，该存储源就不会注册；请求期访问时表现为
    50001，而不是启动失败。

    顺序：按 row.type 查实现 → build_param → service.init → test_connection。
    """
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
    """对应 StorageSourceInitializer.setApplicationContext() 中的存储源循环。

    由 lifespan 启动时调用一次。执行完成后 registry 才有内容，
    /api/storage/list、/api/site/config/storage 才能取到 service。

    查询全部存储源，不筛 enable：Java 同样不筛，禁用状态由 /api/storage/list 的
    SQL 过滤。逐条查询 configs、创建 service 并注册；单条失败记录 error 日志后
    继续处理下一条，不中断启动。整个装配过程共用一个短会话。
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
