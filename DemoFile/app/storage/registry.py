"""一存储源一实例的注册中心，对应 Java 的 StorageSourceContext。

Java 通过 @Scope(PROTOTYPE) 和两个静态 Map 保证每个存储源一个 service 对象；
这里用 dict 保存同样的映射。loader 在启动时注册，路由按 storage_id 或
storage_key 取用。
"""
from typing import Any

from app.core.errors import BizException, ErrorCode
from app.storage.base import AbstractBaseFileService

# Map<存储源 ID, 存储源 Service>
_services: dict[int, AbstractBaseFileService] = {}
# Map<存储源 key, 存储源 ID>
_key_to_id: dict[str, int] = {}


def register(storage_key: str, service: AbstractBaseFileService) -> None:
    """对应 Java StorageSourceContext.init 末尾的两次 Map.put。

    service 必须先 init()，否则 storage_id 为空。
    """
    if service.storage_id is None:
        raise ValueError("注册前必须先init()")
    _services[service.storage_id] = service
    _key_to_id[storage_key] = service.storage_id


def get_by_storage_id(storage_id: int) -> AbstractBaseFileService:
    """按 id 取服务，取不到抛 BizException(INVALID_STORAGE_SOURCE)（50001）。

    对应 Java getByStorageId → InvalidStorageSourceBizException。
    """
    service = _services.get(storage_id)
    if service is None:
        raise BizException(ErrorCode.INVALID_STORAGE_SOURCE)
    return service


def get_by_storage_key(storage_key: str) -> AbstractBaseFileService | None:
    """按 key 取服务，取不到返回 None。

    对应 Java getByStorageKey。调用方（SPA 回退路由）用它判断 URL 第一段是否为
    存储源 key，不匹配是正常分支，因此这里不抛异常。
    """
    storage_id = _key_to_id.get(storage_key)
    if storage_id is None:
        return None
    return get_by_storage_id(storage_id)


def destroy(storage_id: int) -> None:
    """移除注册项并调用 service.destroy()，对应 Java StorageSourceContext.destroy。

    Java 先从 map 中 remove，拿到对象后才调用 destroy，这里保持一致。
    """
    service = _services.pop(storage_id, None)
    if service is None:
        return
    if service.storage_key is not None:
         _key_to_id.pop(service.storage_key, None)
    service.destroy()


def all_services() -> dict[int, AbstractBaseFileService]:
    """返回注册表的浅拷贝，供启动日志和测试断言使用。"""
    return dict(_services)
