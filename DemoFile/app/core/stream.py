"""手写 HTTP Range 支持。

对应 Java core/util/RequestHolder.writeFile()。

Java 的本地存储（LocalServiceImpl.downloadToStream）并不手写 Range：它返回
ResponseEntity<Resource>，由 Spring MVC 的 HttpEntityMethodProcessor 根据 Range
头生成 206 + ResourceRegion，解析失败转 416。本项目的本地存储直接返回
FileResponse，同样由框架处理。

真正手写 Range 的是 RequestHolder.writeFile()，调用方全是远程存储源
（FTP/SFTP/WebDAV/S3/GDrive/OneDrive/UpYun）：它们只有 InputStream，无法 seek，
只能自行解析 Range、置 206 并按段拷贝。本文件即 writeFile 的 Python 版。

HTTP Range 协议（RFC 9110 §14）：
    请求：bytes=0-4     闭区间，含 0 和 4，共 5 字节
          bytes=10-    从 10 到结尾
          bytes=-10    最后 10 字节（suffix）
    响应：可满足 → 206 Partial Content + Content-Range: bytes start-end/total，
          Content-Length = end-start+1
          完全不可满足（start ≥ 文件大小）→ 416 + Content-Range: bytes */total
          所有响应带 Accept-Ranges: bytes
    宽容规则：
          end 超出尾部 → 截断到 size-1，不报错
          畸形/无法解析 → 按 RFC 忽略 Range 头，回 200 全文
          （Starlette 对畸形返回 400；Spring MVC 解析失败返回 416；本实现遵循
          RFC。Java writeFile 走 HttpRange.parseRanges，畸形异常会冒到全局，
          只 catch IOException，最终返回 500。）
    多段：bytes=0-4,10-19 规范要求 multipart/byteranges；Java 取第一段，
          本实现同样只取第一段。

大文件不读入内存：generator + seek + 64KB 分块（与 Starlette responses.py 的
chunk_size 一致）。open() 放在 generator 内，使句柄生命周期与响应一致：客户端
断连 → generator close → with 退出 → 句柄释放。

与 Java 的一处刻意偏离：start ≥ size 时 Java 会把 end 截到 size-1，导致
Content-Length 为负数（ZFile 未处理）；本实现返回 416。

调用链：proxy_router（读取 Range 头）→ LocalServiceImpl.download_to_stream
        → build_file_response。
"""

from collections.abc import Iterator
from pathlib import Path
from urllib.parse import quote

from fastapi.responses import Response, StreamingResponse

#: 分块大小。和 Starlette 内部一致（responses.py 也是 64 * 1024）。
CHUNK_SIZE = 64 * 1024


class RangeNotSatisfiable(Exception):
    """416 的信号，携带文件大小 —— 响应要拼 `Content-Range: bytes */{size}`。"""

    def __init__(self, file_size: int) -> None:
        self.file_size = file_size
        super().__init__(f"range not satisfiable, file_size={file_size}")


def parse_range(range_header: str | None, file_size: int) -> tuple[int, int] | None:
    """解析 Range 请求头 → 闭区间 (start, end)。

    None 表示没带、畸形或应忽略，调用方回 200 全文。
    规则（顺序不可调换）：
      - None / 空串 / strip 后为空 → None
      - 不以 'bytes=' 开头（大小写敏感，与 Java 一致）→ None
      - 去掉 'bytes=' 前缀后按 ',' 切取第一段并 strip：'bytes= 0-4' → '0-4'，
        'bytes=0-4,10-19' → '0-4'
      - 按 '-' 分两半：
          "start-end"：两半都是数字 → (start, end)；start > end（如 5-2）→ None
          "start-"  ：前半是数字、后半为空 → end = file_size - 1
          "-suffix" ：前半为空、后半是数字 → start = max(0, file_size - suffix)，
                      end = file_size - 1（suffix ≥ 文件大小时取整个文件）
          其余（无 '-'、非纯数字、带符号如 '+5'/'-10'）→ None
      - file_size == 0 → 抛 RangeNotSatisfiable（空文件无任何可满足区间）
      - start >= file_size → 抛 RangeNotSatisfiable（Java 这里会产生负长度，本实现 416）
      - end = min(end, file_size - 1)（越尾截断）
    """
    if range_header is None:
        return None
    header = range_header.strip()
    if not header.startswith("bytes="):
        return None
    spec = header[len("bytes="):].split(",",1)[0].strip()
    before, dash, after = spec.partition("-")
    if not dash:
        return None
    if before and after:
        if not (before.isdigit() and after.isdigit()):
            return None
        start,end = int(before), int(after)
        if start > end:
            return None
    elif after == "" and before.isdigit():
        start,end = int(before), file_size-1
    elif before == "" and after.isdigit():
        start, end = max(0, file_size-int(after)),file_size-1
    else:
        return None
    if file_size ==0 or start >= file_size:
        raise RangeNotSatisfiable(file_size)
    return start,min(end,file_size-1)


def iter_range(file_path: Path, start: int, end: int) -> Iterator[bytes]:
    """闭区间 [start, end] 的分块生成器。按 CHUNK_SIZE 切，文件不进内存。

    start > end（空文件 0,-1 / 空区间）直接返回，不打开文件。读取时若 chunk 为空
    （文件被截短等意外）立即停止，避免死循环。yield 必须位于 with 块内：流式响应
    边发边读，句柄需存活到响应结束。
    """
    if start > end:
        return
    remaining = end-start+1
    with open(file_path, "rb") as f:
        f.seek(start)
        while remaining>0:
            chunk = f.read(min(CHUNK_SIZE, remaining))
            if not chunk:
                break
            remaining-=len(chunk)
            yield chunk


def content_disposition(disposition_type: str, filename: str) -> str:
    """拼 Content-Disposition 头（RFC 5987 中文名）。

    复刻 Starlette FileResponse 的输出格式：quoted = quote(filename)（urllib.parse，
    默认 safe='/'；文件名中不应出现 '/'）；quoted != filename 时使用
    ``filename*=utf-8''{quoted}``，否则使用普通 filename 参数。
    对拍基准：attachment; filename*=utf-8''%E8%AF%B4%E6%98%8E.txt
    """
    quoted = quote(filename)
    if quoted != filename:
        return f"{disposition_type}; filename*=utf-8''{quoted}"
    return f'{disposition_type}; filename="{filename}"'


def build_file_response(
    file_path: Path,
    *,
    mime: str,
    disposition_type: str,
    range_header: str | None = None,
) -> Response:
    """组装 200 / 206 / 416 三种响应。对应 Java writeFile 的响应部分。

    三种响应都带 accept-ranges: bytes 与 content-disposition。Range 不可满足时
    返回 416，Content-Range 写作 ``bytes */{size}``（Starlette 的版本缺少 "bytes "
    前缀；RFC 9110 的 unsatisfied-range 为 "bytes */" + 总长）。
    无 Range 或 Range 应忽略时返回 200 全文；否则返回 206，并补
    Content-Range: bytes {start}-{end}/{file_size}。Content-Length 只计算本段长度
    （空文件为 0）。

    刻意不做：If-Range / ETag / Last-Modified 协商（本地 FileResponse 由框架处理，
    这里不重复实现）；多段 multipart（Java 也只取第一段）。
    """
    file_size = file_path.stat().st_size
    headers = {
        "accept-ranges":"bytes",
        "content-disposition":content_disposition(disposition_type,file_path.name),
    }
    try:
        rng = parse_range(range_header,file_size)
    except RangeNotSatisfiable:
        headers["content-range"] = f"bytes */{file_size}"
        return Response(status_code=416, headers=headers)

    if rng is None:
        start,end,status = 0,file_size-1,200
    else:
        start,end = rng
        status = 206
        headers["content-range"] = f"bytes {start}-{end}/{file_size}"

    headers["content-length"] = str(end-start+1)
    return StreamingResponse(
        iter_range(file_path,start,end),
        status_code=status,
        media_type=mime,
        headers=headers,
    )
