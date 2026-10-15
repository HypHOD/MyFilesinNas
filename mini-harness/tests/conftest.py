"""测试基础设施：每个测试独立事件循环，避免跨测试共享 loop。

用 ``@run_async`` 把协程测试包成同步测试，零插件依赖即可跑 ``pytest``。
"""

from __future__ import annotations

import asyncio
import functools
from collections.abc import Callable
from typing import Any


def run_async(fn: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        return asyncio.run(fn(*args, **kwargs))

    return wrapper
