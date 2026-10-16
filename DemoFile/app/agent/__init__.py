"""agent 接入层：mini-harness 装配 + DeepSeek provider + 存储工具。

分两步走（对应仓库 README 路线图第 3 条「agent 接入进行存储管理」）：
  Phase C（当前）：scripts/agent_console.py 在终端里跑通 provider + 工具；
  Phase A（后续）：嵌入后端，暴露 /api/agent 的 HTTP/SSE 给前端。

mini-harness 是仓库内的独立包（MyFilesinNas/mini-harness，零依赖）。
未 pip install -e 时这里兜底把仓库路径加进 sys.path —— monorepo 布局定死
（本文件往上第三层就是仓库根），写死即可。
"""

import importlib.util
import sys
from pathlib import Path

if importlib.util.find_spec("mini_harness") is None:
    _REPO_ROOT = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(_REPO_ROOT / "mini-harness"))
