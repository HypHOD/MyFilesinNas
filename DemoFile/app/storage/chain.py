"""文件列表责任链。对应 Java module/storage/chain/ 包。

为什么要有这一层：接口的"业务"其实只有一行 —— service.file_list(path)。
但一次请求前后夹着 5 件横切的事：能不能进这个目录、要不要密码、哪些要藏起来、
怎么排序、能不能给下载地址。Java 用 Commons Chain 把它们做成 5 个 Command + 执行器，
好处是这些事各自独立、顺序可查、可插拔。

Python 版就是"一个 list of callables"：命令拿到同一个 FileContext，各自读/改自己
负责的字段。Commons Chain 的 Command 返回 true 可中断整条链 —— 5 个命令没有任何
一个用过（都返回 false），所以不搬 stop 语义，for 循环就够。这正是"设计模式的价值
不在模式本身，而在它解决的问题"：用 Python 表达同一个设计，7 个文件的框架依赖
消失了，设计本身还在。

数据流：
    router 组装 ctx（storage_id / 请求 / 原始列表 / service）
      → execute_file_chain(ctx)
          file_access_permission_verify   只读请求（空实现）
          folder_password_verify          写 password_pattern（空实现）
          file_hidden                     改 file_item_list（空实现）
          file_sort                       改 file_item_list（本步实现）
          file_download_permission        改 file_item_list（本步实现）
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
    """对应 FileContext.java：责任链的共享状态（可变载体）。

    用途：router 组装 → 命令们就地读写 → router 回收结果（file_item_list /
    password_pattern）。为什么用 dataclass 而不是 Pydantic：它是**函数间的可变载体**，
    不是序列化边界 —— 命令就是要就地改它（排序换 list、无权限抹 url、密码写表达式）。
    Pydantic 的定位是"校验 + 序列化"，拿来当可变传参载体是跟工具拧着来。
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


# 责任链的组装：对应 FileChain.init() 那 5 行 addCommand。顺序就是语义 ——
# 先鉴权、再密码、再隐藏、再排序（少排要被藏掉的）、最后下载权限。
COMMANDS: list[Callable[[FileContext], None]] = [
    file_access_permission_verify,
    folder_password_verify,
    file_hidden,
    file_sort,
    file_download_permission,
]


def execute_file_chain(ctx: FileContext) -> FileContext:
    """对应 FileChain.execute()：按 COMMANDS 顺序执行，返回同一个 ctx。

    用途：router 组装完 ctx 后唯一的调用点。命令之间不互相调用、不返回值 ——
    结果全在 ctx 里（就地改），返回值只是为了方便链式书写（Java 也返回 content）。

    规格：
      - for command in COMMANDS: command(ctx)
      - return ctx
      - 命令抛出的异常（如将来的密码错误）不在这里捕获 —— 冒泡到全局异常处理器，
        BizException → 响应信封的设计在 chain 之外依然成立

    TODO 写实现
    """
    # raise NotImplementedError
    for command in COMMANDS:
        command(ctx)
    return ctx
