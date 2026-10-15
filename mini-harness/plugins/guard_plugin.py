"""示例插件：在 tools/pre-execute 拦截危险调用。

展示 waterfall 的拦截语义：命中规则直接返回 ``PreToolDeny``（不调用 ``next()``,
即短路整条链），deny 单调不可翻回；工具不会执行，模型只看到
``Error: ...`` 文本并据此继续。

守则是演示性质的：拒绝一切含 ``..`` 或指向目录外绝对路径的 read_file 调用。
"""

from __future__ import annotations

from typing import Any

from mini_harness.container import Context
from mini_harness.tools import PreToolDeny


class GuardPlugin:
    """拒绝路径穿越类的 read_file 调用。"""

    name = "guard"

    def apply(self, ctx: Context) -> None:
        async def guard(view: Any, next: Any) -> Any:
            if view.name == "read_file" and _looks_like_escape(view.arguments):
                return PreToolDeny(
                    reason=f"guard: path {view.arguments.get('path')!r} looks like a traversal"
                )
            return await next()

        ctx.on("tools/pre-execute", guard)


def _looks_like_escape(arguments: dict) -> bool:
    path = str(arguments.get("path", ""))
    return ".." in path or path.startswith("/")
