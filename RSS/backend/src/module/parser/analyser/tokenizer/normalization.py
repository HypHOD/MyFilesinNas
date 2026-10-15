"""解析前的输入归一化（标题解析器共用）。"""

from __future__ import annotations

import re

_FILE_EXTENSION = re.compile(r"\.(mp4|mkv|avi|ass|srt|ssa|sub)$", re.I)


def normalize(raw: str) -> str:
    value = raw.strip().replace("\n", " ")
    # 全角方括号是结构括号，统一为半角；全角斜杠/圆括号属于标题标点，保留
    value = value.replace("【", "[").replace("】", "]")
    return _FILE_EXTENSION.sub("", value)
