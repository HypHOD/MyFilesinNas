"""agent 接入层：mini-harness 装配 + DeepSeek provider + 存储工具。

装配入口有两处：scripts/agent_console.py（终端调试）与 app/agent/host.py
（后端 HTTP/SSE 宿主）。

mini-harness 是仓库内的独立包（MyFilesinNas/mini-harness，零依赖）。
未执行 pip install -e 时，这里兜底把仓库路径加入 sys.path —— monorepo 布局固定，
本文件向上第三层即仓库根。
"""

import importlib.util
import sys
from pathlib import Path

if importlib.util.find_spec("mini_harness") is None:
    _REPO_ROOT = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(_REPO_ROOT / "mini-harness"))
