"""路径 / URL 拼接工具。对应 Java 的 core/util/StringUtils.java + core/util/FileUtils.java。

Java 那两个类同时管 URL、路径、字符串三件事，Python 侧只搬存储层真正要用的几个函数，
用到再加（和 ErrorCode 一个策略）。

⚠️ 这几个函数的边界行为是**刻意对齐 Java** 的。"看起来更干净"的改法
（比如用 os.path.join、pathlib）会在这里埋下不一致，改动前先回头看 Java 原实现。
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
    """合并连续重复的 '/'，但不动 "://" 头部（否则 http:// 会被压成 http:/）。

    对应 Java: StringUtils.removeDuplicateSlashes。
    注意它**不去结尾的 '/'**（那是另一个函数 removeDuplicateSlashesAndTrimEnd 的活）。
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

    规则（照抄，别"优化"）：
      - 结果**永远是绝对路径**：开头必有一个 '/'
      - 空串 / None 段跳过，但分隔符是按**下标**加的，多余的空档交给
        _remove_duplicate_slashes 收掉
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

    Java 是**按 '/' 分段**再逐段 hutool `URLEncodeUtil.encodeAll`，
    效果等价于 `quote(safe="/")`：空格 -> %20，中文 -> UTF-8 三字节。
    （这一条步骤 6/7 会拿真前端再核对一次：URL 里的中文一旦编错，下载就 404。）
    """
    if not path:
        return path
    return quote(path, safe="/")
