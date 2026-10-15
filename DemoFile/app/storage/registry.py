"""一存储源一实例的注册中心。对应 Java 的 StorageSourceContext（去掉 Spring 反射那半）。

Java 用 @Scope(PROTOTYPE) + 两个静态 Map 实现"每个存储源一个 service 对象"，
Python 直接 dict 就够 —— 没有框架魔法，也不需要 ConcurrentHashMap。

步骤 5 的 loader 负责往里注册；步骤 6 的路由按 storage_id / storage_key 取。
"""
from typing import Any

from app.core.errors import BizException, ErrorCode
from app.storage.base import AbstractBaseFileService

# Map<存储源 ID, 存储源 Service>
_services: dict[int, AbstractBaseFileService] = {}
# Map<存储源 key, 存储源 ID>
_key_to_id: dict[str, int] = {}


def register(storage_key: str, service: AbstractBaseFileService) -> None:
    """注册（对应 Java StorageSourceContext.init 的最后两行 Map.put）。

    TODO 写实现（两个 dict 都要写；注意 service.storage_id 可能为 None，先断言掉）
    """
    # raise NotImplementedError
    if service.storage_id is None:
        raise ValueError("注册前必须先init()")
    _services[service.storage_id] = service
    _key_to_id[storage_key] = service.storage_id


def get_by_storage_id(storage_id: int) -> AbstractBaseFileService:
    """按 id 取。取不到**抛异常**：BizException(ErrorCode.INVALID_STORAGE_SOURCE)

    对应 Java getByStorageId → InvalidStorageSourceBizException（50001）。

    TODO 写实现
    """
    # raise NotImplementedError
    service = _services.get(storage_id)
    if service is None:
        raise BizException(ErrorCode.INVALID_STORAGE_SOURCE)
    return service


def get_by_storage_key(storage_key: str) -> AbstractBaseFileService | None:
    """按 key 取。取不到返回 **None**，不是错误。

    对应 Java getByStorageKey —— 它的调用方（步骤 11 的 SPA 回退路由）拿它判断
    "URL 第一段到底是不是存储源 key"，不匹配是正常分支，所以**别在这里抛异常**。

    TODO 写实现
    """
    # raise NotImplementedError
    storage_id = _key_to_id.get(storage_key)
    if storage_id is None:
        return None
    return get_by_storage_id(storage_id)


def destroy(storage_id: int) -> None:
    """移除注册项并调 service.destroy()。对应 Java StorageSourceContext.destroy（312-322 行）。

    TODO 写实现（Java 是先从 map 里 remove，拿到的对象非空才调 destroy）
    """
    # raise NotImplementedError
    service = _services.pop(storage_id, None)
    if service is None:
        return
    if service.storage_key is not None:
         _key_to_id.pop(service.storage_key, None)
    service.destroy()


def all_services() -> dict[int, AbstractBaseFileService]:
    """返回当前注册表的浅拷贝（启动日志、测试断言用）。

    TODO 写实现（返回拷贝，别把内部 dict 漏出去）
    """
    # raise NotImplementedError
    return dict(_services)
