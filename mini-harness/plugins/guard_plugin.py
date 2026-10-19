"""示例插件：在 tools/pre-execute 拦截危险调用。

命中规则直接返回 ``PreToolDeny``（不调用 ``next()``，短路整条链）；deny 为终态，
工具不会执行，模型只看到 ``Error: ...`` 文本并据此继续。

规则为演示性质：拒绝一切含 ``..`` 或指向目录外绝对路径的 read_file 调用。
"""

from __future__ import annotations

from typing import Any

from mini_harness.container import Context
from mini_harness.tools import PreToolDeny


class GuardPlugin:
    """拒绝路径穿越类的 read_file 调用。"""

    name = "guard"

    def apply(self, ctx: Context) -> None:
        # 监听器签名固定为 (..., next)：调用 await next() 透传到下一层；
        # 直接返回决策对象则短路，后续监听器与 default 都不执行。
        async def guard(view: Any, next: Any) -> Any:
            if view.name == "read_file" and _looks_like_escape(view.arguments):
                # 返回 Deny：tools.run_tool_pipeline 收到后直接产出 Error 结果，
                # 真实 execute 不会被调用。
                return PreToolDeny(
                    reason=f"guard: path {view.arguments.get('path')!r} looks like a traversal"
                )
            return await next()

        ctx.on("tools/pre-execute", guard)


def _looks_like_escape(arguments: dict) -> bool:
    # 仅做字面量检查；真正的安全边界是 demo_tools._read_file 中的 resolve 校验。
    path = str(arguments.get("path", ""))
    return ".." in path or path.startswith("/")
