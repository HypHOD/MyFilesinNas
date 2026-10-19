"""文件列表责任链的 5 个命令，对应 Java module/storage/chain/command/ 包。

命令形态统一：读取 FileContext 中自己关心的字段，就地修改自己负责的字段，
不返回结果，也不感知其它命令。

当前实现状态：

    file_access_permission_verify   占位（filter_config 表未接入）
    folder_password_verify          占位（password_config 表未接入）
    file_hidden                     占位（filter_config 表未接入）
    file_sort                       已实现
    file_download_permission        已实现

占位函数保留在链中，是为了固定插入点和执行顺序；接入配置表时只填函数体，
chain.py 不需要改动。
"""

from __future__ import annotations

import re
from functools import cmp_to_key
from typing import TYPE_CHECKING

from app.core.db import SessionLocal
from app.storage.enums import FileOperatorType, FileType
from app.storage.schemas import FileItemResult

if TYPE_CHECKING:
    # 只为类型标注 import（命令运行时不需要 FileContext 类本身）。
    # 这样 commands ←→ chain 只有 chain → commands 这一条运行时依赖，不会循环 import。
    from app.storage.chain import FileContext


# ── 前三个：等待配置表接入 ──────────────────────────────────────


def file_access_permission_verify(ctx: FileContext) -> None:
    """对应 FileAccessPermissionVerifyCommand：校验当前目录是否禁止访问。

    接入 filter_config 后，命中"不可访问路径"规则时抛
    StorageSourceFileForbiddenAccessBizException。当前没有规则表，空实现即正确行为。
    """
    return None


def folder_password_verify(ctx: FileContext) -> None:
    """对应 FolderPasswordVerifyCommand：目录密码校验。

    接入 password_config 后：operator 拥有 IGNORE_PASSWORD 权限时放行；否则校验
    密码表达式，失败抛 41020（需要密码）或 41021（密码错误），通过时把表达式写入
    ctx.password_pattern（响应体 passwordPattern 的来源）。

    密码按包含用户根的完整路径匹配，与 file_list 同属相对入参处理：
        fullPath = concat(fileService.get_current_user_base_path(), path)
    """
    return None


def file_hidden(ctx: FileContext) -> None:
    """对应 FileHiddenCommand：按过滤规则隐藏文件。

    接入 filter_config 后，逐项匹配 file.get_full_path()，命中的项从
    ctx.file_item_list 中移除。当前没有规则表，空实现即正确行为。
    """
    return None


# ── 已实现 ──────────────────────────────────────────────────────


def file_sort(ctx: FileContext) -> None:
    """对应 FileSortCommand：按请求的 orderBy / orderDirection 排序。

    排序由后端完成：前端把排序参数放进请求，返回的列表已经有序。参数为空时保持
    service 给出的原顺序。

    实现与 Java 的差异：Java 先 new ArrayList 拷贝再排序，Python 的 sorted()
    天然返回新列表。比较逻辑委托给 _compare_file_item，用 cmp_to_key 适配
    Java 风格的比较器。
    """
    req = ctx.file_list_request
    if not req.orderBy or not req.orderDirection:
        return 
    ctx.file_item_list = sorted(
        ctx.file_item_list,
        key=cmp_to_key(
            lambda a,b: _compare_file_item(a,b,req.orderBy, req.orderDirection)
        ),
    )


def file_download_permission(ctx: FileContext) -> None:
    """对应 FileDownloadPermissionCommand：无下载且无预览权限时清空所有 url。

    前端只通过 url 是否存在判断能否下载，权限判断全部在后端完成。任一权限为真时
    保留 url，否则把列表中每个 item.url 置 None。

    权限查询位于 modules 层，storage → modules 属于向上依赖，沿用函数内延迟
    import。两次查询共用一个短会话；Java 对授权行有缓存，这里先保证正确性。
    ctx.operator_user_id 在普通模式下为 None，权限函数内部会回退到当前登录用户。
    """
    from app.modules.storage.service import has_user_storage_operator_permission

    with SessionLocal() as db:
        has_download = has_user_storage_operator_permission(
            db, ctx.operator_user_id,ctx.storage_id,FileOperatorType.DOWNLOAD
        )
        has_preview = has_user_storage_operator_permission(
            db,ctx.operator_user_id,ctx.storage_id,FileOperatorType.PREVIEW
        )
    if has_download or has_preview:
        return
    for item in ctx.file_item_list:
        item.url = None


# ── 排序辅助 ────────────────────────────────────────────────────


def _compare_file_item(
    a: FileItemResult, b: FileItemResult, order_by: str, order_direction: str
) -> int:
    """对应 Java FileComparator.compare：负数表示 a 在前，正数表示 b 在前。

    file_sort 通过 cmp_to_key 将其作为 sorted 的比较函数。

    规则与 Java 一致：
      1. 类型不同时文件夹恒在前，该分支不受 asc/desc 影响（Java 在类型分支直接
         返回，尚未进入取反逻辑）。
      2. 同类型时按 order_by 取值：time 比时间，size 比大小，其余按
         _natural_sort_key(name) 比较。None 语义为两边 None 相等、单个 None 在前
         （hutool CompareUtil.compare 的行为；文件夹的 size 为 None）。
      3. order_direction == "desc" 时取反，仅作用于同类型分支。
    """
    if a.type!= b.type:
        return -1 if a.type == FileType.FOLDER else 1

    if order_by == "time":
        result = _compare_values(a.time,b.time)
    elif order_by == "size":
        result = _compare_values(a.size,b.size)
    else:
        key_a = _natural_sort_key(a.name)
        key_b = _natural_sort_key(b.name)
        result = (key_a>key_b) - (key_a < key_b)
    return result if order_direction == "asc" else -result
        


_NUMBER_SEGMENT = re.compile(r"(\d+)")


def _natural_sort_key(name: str) -> tuple:
    """Windows 风格自然排序键，对应 Java NaturalOrderComparator 的简化实现。

    让 "file2" 排在 "file10" 之前。Java 是逐字符的 C 风格算法，这里用分段元组
    近似，差异只出现在前导零计数以及 '.' / ',' 被当作数字的极边缘情况。

    _NUMBER_SEGMENT.split(name) 按"文字/数字"交替切段，每段映射为
    (0, int(seg)) 或 (1, seg)。外层 rank 是必要的：Python 3 中 int 与 str 不能
    直接比较；rank 取"数字 0 < 文字 1"对应 Java 的字符码点顺序。Java 注释声称
    不区分大小写，但实现是逐字符码点比较，这里以实现为准。
    """
    return tuple(
        (0,int(segment)) if segment.isdigit() else (1,segment) for segment in _NUMBER_SEGMENT.split(name)
    )

def _compare_values(a,b) -> int:
    """按 hutool CompareUtil.compare 的语义比较可空值：None 视为最小。"""
    if a is None and b is None:
        return 0
    if a is None:
        return -1
    if b is None:
        return 1
    return (a>b)-(a<b)