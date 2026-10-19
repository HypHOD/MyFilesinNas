"""路径 / URL 拼接工具。

对应 Java 的 core/util/StringUtils.java + core/util/FileUtils.java。Java 这两个类
同时承担 URL、路径与字符串处理；这里只实现存储层实际使用的函数。

这些函数的边界行为刻意与 Java 保持一致。不要用 os.path.join / pathlib 等
"看起来更干净"的方式改写；修改前先对照 Java 原实现。
"""

from urllib.parse import quote

PROTOCOL_MARKER = "://"


def trim_start_slashes(path: str | None) -> str | None:
    """去掉开头所有 '/'。Java: StringUtils.trimStartSlashes"""
    return path.lstrip("/") if path is not None else None


def trim_end_slashes(path: str | None) -> str | None:
    """去掉结尾所有 '/'。Java: StringUtils.trimEndSlashes"""
    return path.rstrip("/") if path is not None else None


def trim_slashes(path: str | None) -> str | None:
    """去掉首尾所有 '/'。Java: StringUtils.trimSlashes"""
    return path.strip("/") if path is not None else None


def _remove_duplicate_slashes(path: str) -> str:
    """合并连续重复的 '/'，但保留 "://" 头部（否则 http:// 会被压成 http:/）。

    对应 Java: StringUtils.removeDuplicateSlashes。它不去结尾的 '/'；
    去尾斜杠由 removeDuplicateSlashesAndTrimEnd 负责。
    """
    if not path:
        return path

    out: list[str] = []
    start = 0

    protocol_index = path.find(PROTOCOL_MARKER)
    if protocol_index > -1:
        scheme_start = 0
        while scheme_start < protocol_index and path[scheme_start] == "/":
            scheme_start += 1
        out.append(path[scheme_start:protocol_index] + PROTOCOL_MARKER)
        start = protocol_index + len(PROTOCOL_MARKER)

    last = ""
    for ch in path[start:]:
        if ch != "/" or last != "/":
            out.append(ch)
            last = ch
    return "".join(out)


def concat(*parts: str | None) -> str:
    """拼接路径 / URL。对应 Java: StringUtils.concat(strs)。

    规则（与 Java 保持一致，不要改写）：
      - 结果永远是绝对路径：开头必有一个 '/'
      - 空串 / None 段跳过，但分隔符按原始下标添加，多余的空档交给
        _remove_duplicate_slashes 处理
      - "://" 头部不被破坏 → concat("http://a.com", "/x") == "http://a.com/x"

    >>> concat("/data", "/alice/", "/sub", "a.txt")
    '/data/alice/sub/a.txt'
    >>> concat("http://a.com", "/pd", "local", "/a b.txt")
    'http://a.com/pd/local/a b.txt'
    """
    buf: list[str] = ["/"]
    last_index = len(parts) - 1
    for i, part in enumerate(parts):
        if not part:
            continue
        buf.append(part)
        if i != last_index:
            buf.append("/")
    return _remove_duplicate_slashes("".join(buf))


def get_name(path_and_name: str | None) -> str | None:
    """取最后一段（文件名）。对应 Java: FileUtils.getName。

    get_name("/a/b.txt") -> "b.txt"；get_name("/a/") -> ""；get_name("b.txt") -> "b.txt"
    """
    if path_and_name is None:
        return None
    return path_and_name.rpartition("/")[2]


def get_parent_path(path_and_name: str | None) -> str:
    """取父目录，取不到就给 '/'。对应 Java: FileUtils.getParentPath。

    get_parent_path("/a/b.txt") -> "/a"
    get_parent_path("/a")       -> "/"
    get_parent_path("b.txt")    -> "/"
    """
    path = trim_end_slashes(path_and_name or "") or ""
    index = path.rfind("/")
    parent = trim_end_slashes(path[:index]) if index > 0 else ""
    return parent or "/"


def encode_ignore_slashes(path: str | None) -> str | None:
    """percent-encode，但保留 '/' 当分隔符。对应 Java: StringUtils.encodeAllIgnoreSlashes。

    Java 按 '/' 分段后逐段调用 hutool ``URLEncodeUtil.encodeAll``，
    效果等价于 ``quote(safe="/")``：空格 → %20，中文 → UTF-8 三字节。
    中文编码错误会直接导致下载 404。
    """
    if not path:
        return path
    return quote(path, safe="/")
