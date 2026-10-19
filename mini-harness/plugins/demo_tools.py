"""示例插件：注册 read_file 与 echo 两个工具。

工具即插件：构造 ToolDefinition（含 JSON Schema 与执行函数）交给 ToolsPlugin
装配；注册返回 disposer，随插件卸载自动撤销。

read_file 被限制在 ``allowed_dir`` 内（resolve 后前缀检查），是工具侧的安全
边界；guard_plugin 在流水线层拦截，两者互补。
"""

from __future__ import annotations

from pathlib import Path

from mini_harness.tools import ToolDefinition, ToolsPlugin


def _read_file(allowed_dir: Path) -> ToolDefinition:
    root = allowed_dir.resolve()

    def execute(args: dict) -> str:
        # 先 resolve 成规范路径（消掉 .. 与符号链接），再校验仍在根目录内。
        # 这是 guard_plugin 之外的第二道防线：那里拦模型参数，这里拦实际文件访问。
        requested = (root / str(args.get("path", ""))).resolve()
        if not requested.is_relative_to(root):
            raise ValueError(f"path escapes allowed dir: {args.get('path')!r}")
        return requested.read_text(encoding="utf-8")

    # parameters 是发给模型的 JSON Schema；execute 永远不会出现在 schema 里。
    return ToolDefinition(
        name="read_file",
        description="Read a text file relative to the demo directory.",
        parameters={
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Relative file path"}},
            "required": ["path"],
        },
        execute=execute,
        is_concurrency_safe=True,
    )


def _echo() -> ToolDefinition:
    def execute(args: dict) -> str:
        return f"echo: {args.get('text', '')}"

    return ToolDefinition(
        name="echo",
        description="Echo the given text back.",
        parameters={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        execute=execute,
        is_concurrency_safe=True,
    )


def demo_tools_plugin(allowed_dir: Path | str) -> ToolsPlugin:
    """返回预装 read_file/echo 的 ToolsPlugin。"""
    # ToolsPlugin.apply() 提供 ctx.tools；AgentLoopPlugin 依赖它才会激活。
    return ToolsPlugin([_read_file(Path(allowed_dir)), _echo()])
