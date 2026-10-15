"""资源名解析的薄包装：直接转发 tokenizer.classic。

参考实现此处还有引擎选择（classic / preview）与旧模型投影（compat），
本工程固定走 classic、直接返回 ParsedRelease，不再经过 selector 间接层。
"""

import logging

from .tokenizer import ParsedRelease, parse_release_title

logger = logging.getLogger(__name__)


def raw_parser(raw: str) -> ParsedRelease | None:
    parsed = parse_release_title(raw)
    if parsed is None:
        logger.info("Cannot parse resource: %s, skipping.", raw)
    return parsed
