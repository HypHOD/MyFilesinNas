"""文件列表责任链，对应 Java module/storage/chain/ 包。

file_list 本身只有一行调用，但一次请求前后还有 5 件横切逻辑：访问权限、目录密码、
隐藏规则、排序、下载权限。Java 用 Commons Chain 做成 5 个 Command 加执行器；
这里的等价物是 COMMANDS 列表，每个命令读写同一个 FileContext。

Commons Chain 的 Command 可以返回 true 中断整条链，5 个命令都没有使用这一语义，
因此执行器就是一个顺序 for 循环。

数据流：
    router 组装 ctx（storage_id / 请求 / 原始列表 / service）
      → execute_file_chain(ctx)
          file_access_permission_verify   访问权限（占位）
          folder_password_verify          目录密码（占位）
          file_hidden                     隐藏规则（占位）
          file_sort                       排序
          file_download_permission        下载权限
      → ctx.file_item_list / ctx.password_pattern 组响应
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.storage.base import AbstractBaseFileService
from app.storage.commands import (
    file_access_permission_verify,
    file_download_permission,
    file_hidden,
    file_sort,
    folder_password_verify,
)
from app.storage.schemas import FileItemResult

if TYPE_CHECKING:
    # 只为类型标注（storage 层向上引用 modules 层的请求模型）。
    # `from __future__ import annotations` 让标注不在运行时求值，真实 import 不会发生。
    from app.modules.storage.schemas import FileListRequest


@dataclass
class FileContext:
    """对应 FileContext.java：责任链共享的可变状态。

    router 组装后交给命令就地读写，最后回收 file_item_list / password_pattern。
    不用 Pydantic：它是函数间的可变载体，不是序列化边界；命令需要直接替换 list、
    清空 url、写入密码表达式。
    """

    storage_id: int
    file_list_request: FileListRequest
    file_item_list: list[FileItemResult]
    file_service: AbstractBaseFileService
    # 当前目录的密码路径表达式。password_config 未做 → 恒 None，但字段必须在：
    # 响应体 FileInfoResult.passwordPattern 从它来（前端 useFileData.js:99 会读）。
    password_pattern: str | None = None
    # 操作者用户 id：普通模式 None —— 不是漏传，权限查询内部会回退到"当前登录用户"；
    # 分享模式才显式设为分享者的 id（Java 同为 null 默认值）。
    operator_user_id: int | None = None


# 对应 FileChain.init() 的 5 行 addCommand。顺序即语义：先鉴权、再密码、再隐藏、
# 再排序（避免排序已被隐藏的条目）、最后下载权限。
COMMANDS: list[Callable[[FileContext], None]] = [
    file_access_permission_verify,
    folder_password_verify,
    file_hidden,
    file_sort,
    file_download_permission,
]


def execute_file_chain(ctx: FileContext) -> FileContext:
    """对应 FileChain.execute()：按 COMMANDS 顺序执行，返回同一个 ctx。

    命令之间不互相调用、不返回值，结果全部写入 ctx。命令抛出的异常（如密码错误）
    不在这里捕获，交给全局异常处理器转成响应信封。返回值便于链式书写，与 Java
    返回 content 一致。
    """
    for command in COMMANDS:
        command(ctx)
    return ctx
