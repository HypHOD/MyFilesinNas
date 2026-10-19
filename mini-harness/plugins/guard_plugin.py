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
        # waterfall 监听器签名固定为 (..., next)：
        #   - 调 await next() → 交给下一层（透传）
        #   - 直接 return 决策对象 → 短路，后续监听器与 default 都不执行
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
    # 演示级规则（字面量检查）；真正的安全边界在 demo_tools._read_file 里做 resolve 校验。
    path = str(arguments.get("path", ""))
    return ".." in path or path.startswith("/")
