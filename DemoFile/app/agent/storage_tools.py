"""存储工具：把 DemoFile 存储层已有能力暴露给 agent（只包装，不新增行为）。

- 路径入参与 service 层「相对入参族」一致：**相对用户根**（"/"、"/Bangumi"），
  用户身份来自 app.core.context 的 contextvar。宿主必须在**创建 agent 之前**
  set_current_user_id()（CLI = 管理员；Phase A = 登录用户）——agent loop 是
  创建时 create_task 起的常驻任务，contextvar 随创建时刻快照进任务。
- 读工具标记 is_concurrency_safe → agent_loop 里连续读调用可并行；
  写工具（new_folder / rename）保持默认独占屏障。
- 阻塞的文件 IO / DB 查询丢进 asyncio.to_thread；to_thread 会复制当前 context，
  用户身份随之带入工作线程（storage 层查 user_storage_source 拿根目录靠它）。
- 删除 / 移动 / 复制暂不提供：权限模型（19 个 FileOperatorType 还没接进工具层）
  没定之前不给 agent 破坏性能力。
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from mini_harness.tools import ToolDefinition, ToolsPlugin

from app.core.path_utils import concat
from app.storage import registry
from app.storage.base import AbstractBaseFileService
from app.storage.enums import FileType
from app.storage.schemas import FileItemResult

_LIST_CAP = 200


def _service(storage_key: str) -> AbstractBaseFileService:
    service = registry.get_by_storage_key(storage_key)
    if service is None:
        known = [s.storage_key for s in registry.all_services().values()]
        raise ValueError(f"未知存储源 {storage_key!r}；可用: {known or '（注册表为空）'}")
    return service


def _fmt_size(size: int | None) -> str:
    if size is None:
        return "-"
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024:
            return f"{int(value)}B" if unit == "B" else f"{value:.1f}{unit}"
        value /= 1024
    return f"{value:.1f}TB"


def _fmt_item(item: FileItemResult) -> str:
    if item.type == FileType.FOLDER:
        return f"[目录] {item.name}/"
    time_text = item.time.strftime("%Y-%m-%d %H:%M") if item.time else "-"
    return f"[文件] {item.name}  {_fmt_size(item.size)}  {time_text}"


# -- 工具实现（入参是模型给的 JSON dict，出参是进历史的字符串） ---------------


def _list_storage_sources(_args: dict[str, Any]) -> str:
    services = registry.all_services()
    if not services:
        return "注册表为空。先运行 scripts/seed_local_storage.py（新库还需先 init_db.py）。"
    lines = ["key | 名称 | 类型"]
    for service in services.values():
        lines.append(f"{service.storage_key} | {service.name} | {service.get_storage_type().value}")
    return "\n".join(lines)


def _list_files(args: dict[str, Any]) -> str:
    service = _service(str(args["storage_key"]))
    path = str(args.get("path") or "/")
    items = service.file_list(path)
    if not items:
        return f"{path} 下没有内容。"
    items.sort(key=lambda item: (item.type != FileType.FOLDER, item.name))
    header = f"{path} 共 {len(items)} 项："
    if len(items) > _LIST_CAP:
        header = f"{path} 共 {len(items)} 项（只显示前 {_LIST_CAP} 项）："
    return "\n".join([header] + [_fmt_item(item) for item in items[:_LIST_CAP]])


def _file_info(args: dict[str, Any]) -> str:
    service = _service(str(args["storage_key"]))
    path_and_name = str(args["path_and_name"])
    item = service.get_file_item(path_and_name)
    if item is None:
        return f"不存在: {path_and_name}"
    return f"{_fmt_item(item)}  path={item.path}"


def _new_folder(args: dict[str, Any]) -> str:
    service = _service(str(args["storage_key"]))
    path = str(args.get("path") or "/")
    name = str(args["name"])
    ok = service.new_folder(path, name)
    return f"已创建文件夹 {concat(path, name)}" if ok else f"创建失败: {concat(path, name)}"


def _rename(args: dict[str, Any]) -> str:
    service = _service(str(args["storage_key"]))
    path = str(args.get("path") or "/")
    name = str(args["name"])
    new_name = str(args["new_name"])
    item = service.get_file_item(concat(path, name))
    if item is None:
        return f"不存在: {concat(path, name)}"
    if item.type == FileType.FOLDER:
        ok = service.rename_folder(path, name, new_name)
    else:
        ok = service.rename_file(path, name, new_name)
    return (
        f"已重命名 {concat(path, name)} -> {new_name}"
        if ok
        else f"重命名失败: {concat(path, name)}"
    )


def _tool(
    name: str,
    description: str,
    parameters: dict[str, Any],
    impl: Callable[[dict[str, Any]], str],
    *,
    concurrency_safe: bool = False,
) -> ToolDefinition:
    async def execute(args: dict[str, Any]) -> str:
        return await asyncio.to_thread(impl, args)

    return ToolDefinition(
        name=name,
        description=description,
        parameters=parameters,
        execute=execute,
        is_concurrency_safe=concurrency_safe,
    )


def storage_tools() -> list[ToolDefinition]:
    return [
        _tool(
            "list_storage_sources",
            "列出所有存储源。返回的 key 用于其它工具的 storage_key 参数。",
            {"type": "object", "properties": {}, "required": []},
            _list_storage_sources,
            concurrency_safe=True,
        ),
        _tool(
            "list_files",
            "列出存储源中某个目录的内容（文件夹在前，按名称排序）。",
            {
                "type": "object",
                "properties": {
                    "storage_key": {"type": "string", "description": "存储源 key，如 local"},
                    "path": {"type": "string", "description": "相对用户根的目录路径，默认 /"},
                },
                "required": ["storage_key"],
            },
            _list_files,
            concurrency_safe=True,
        ),
        _tool(
            "file_info",
            "查看单个文件或文件夹的详情；不存在时返回「不存在」。",
            {
                "type": "object",
                "properties": {
                    "storage_key": {"type": "string"},
                    "path_and_name": {
                        "type": "string",
                        "description": "相对用户根的完整路径，如 /Bangumi/言叶之庭 (2013)",
                    },
                },
                "required": ["storage_key", "path_and_name"],
            },
            _file_info,
            concurrency_safe=True,
        ),
        _tool(
            "new_folder",
            "在指定目录下新建文件夹（父目录不存在会一并创建）。",
            {
                "type": "object",
                "properties": {
                    "storage_key": {"type": "string"},
                    "path": {"type": "string", "description": "父目录（相对用户根），默认 /"},
                    "name": {"type": "string", "description": "新文件夹名"},
                },
                "required": ["storage_key", "name"],
            },
            _new_folder,
        ),
        _tool(
            "rename",
            "重命名文件或文件夹（同目录内改名，自动区分两者）。",
            {
                "type": "object",
                "properties": {
                    "storage_key": {"type": "string"},
                    "path": {"type": "string", "description": "所在目录（相对用户根），默认 /"},
                    "name": {"type": "string", "description": "当前名称"},
                    "new_name": {"type": "string", "description": "新名称"},
                },
                "required": ["storage_key", "name", "new_name"],
            },
            _rename,
        ),
    ]


def storage_tools_plugin() -> ToolsPlugin:
    return ToolsPlugin(storage_tools())
