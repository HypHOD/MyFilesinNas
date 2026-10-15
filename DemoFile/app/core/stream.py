"""手写 HTTP Range 支持。对应 Java core/util/RequestHolder.writeFile()。先搞清楚一件事 ——

【Java 里谁在做 Range】（读源码读出来的，很反直觉）
    LocalServiceImpl 里**一行 Range 代码都没有**：它的 downloadToStream 返回
    ResponseEntity<Resource>，Range 由 **Spring MVC 框架自动处理**（HttpEntityMethodProcessor：
    见 Range 头就转 206 + ResourceRegion，解析失败转 416）。也就是说 Java 的"本地存储 +
    Range" = 我们 7b 的 FileResponse —— 两边都是框架白送的，代码里看不见。
    真正手写 Range 的是 RequestHolder.writeFile()，调用方全是**远程存储源**（FTP/SFTP/
    WebDAV/S3/GDrive/OneDrive/UpYun）—— 它们手里只有一个 InputStream，交给框架就没法
    seek，只能自己解析、自己置 206、自己按段拷贝。
    所以本文件 = writeFile 的 Python 版；7c 你是在重造框架替你做的事。

【HTTP Range 协议速览（RFC 9110 §14）】
    请求：bytes=0-4     闭区间，含 0 和 4，共 5 字节
          bytes=10-    从 10 到结尾
          bytes=-10    最后 10 字节（suffix；数字含义和前两种相反）
    响应：可满足 → 206 Partial Content + Content-Range: bytes start-end/total，
          Content-Length = end-start+1（只算这一段）
          完全不可满足（start ≥ 文件大小）→ 416 + Content-Range: bytes */total
          任何响应都带 Accept-Ranges: bytes 作"我支持"的广告
    两条宽容规则（★ 测试里会钉）：
          end 超尾 → 截断到 size-1，不是错误
          畸形/看不懂 → 按 RFC 忽略请求头，回 200 全文，不是报错
          （三种实现三种选择：Starlette 畸形→400；Spring MVC 解析失败→416；RFC 要求忽略。
            我们跟 RFC。Java writeFile 走 HttpRange.parseRanges，畸形会在那儿抛异常冒到
            全局（它只 catch IOException）→ 500 —— 又一处我们做得稳的地方。）
    多段：bytes=0-4,10-19 → 规范要求 multipart/byteranges 响应（Starlette 实现了）。
          罕用且复杂，Java 是"集合取第一个" —— ★ 我们跟 Java：只取第一段。

【为什么流式】大文件绝不能读进内存。generator + seek + 64KB 分块 —— Starlette 内部也是
    这么干的（responses.py 里 chunk_size = 64 * 1024，同一个数字）。
    `with open(...)` 写在 generator 里不是笔误：句柄生命周期 = 响应生命周期，
    客户端断连 → generator 被 close → with 退出 → 句柄释放。

【对 Java 的一处刻意偏离】start ≥ size 时，Java writeFile 的 end 被截到 size-1，
    Content-Length = end-start+1 变成**负数**（ZFile 没防）—— 我们回 416。

调用链：proxy_router（从 Header 取 Range）→ LocalServiceImpl.download_to_stream
        → 本模块 build_file_response。
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
    """解析 Range 请求头 → 闭区间 (start, end)；None = 没带/畸形/该忽略 → 调用方回 200 全文。

    规格（顺序别换）：
      ① None / 空串 / strip 后为空 → None
      ② 不以 'bytes=' 开头（大小写敏感，照 Java）→ None
      ③ spec = 去掉 'bytes=' 前缀后、按 ',' 切取第一段再 strip
         （'bytes= 0-4' → '0-4' 容忍前缀后的空格；'bytes=0-4,10-19' → 只留 '0-4'）
      ④ partition('-') 分两半：
           "start-end"：两半都 isdigit → start, end；start > end（倒置如 5-2）→ None
           "start-"  ：前半 isdigit、后半为空 → end = file_size - 1
           "-suffix" ：前半为空、后半 isdigit → start = max(0, file_size - suffix)，
                        end = file_size - 1（suffix ≥ 文件大小 → 整个文件）
           其余（没有 '-'、非纯数字、带符号的 '+5'/'-10'）→ None
      ⑤ file_size == 0 → 抛 RangeNotSatisfiable（空文件什么都满足不了）
      ⑥ start >= file_size → 抛 RangeNotSatisfiable（★ Java 在这出负数长度，我们 416）
      ⑦ end = min(end, file_size - 1)（越尾截断）→ 返回 (start, end)

    TODO 写实现
    """
    # raise NotImplementedError
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

    规格：
      - start > end（空文件 0,-1 / 空区间）→ 直接 return，连文件都不用打开
      - remaining = end - start + 1（要发的总字节数）
      - with open(file_path, "rb") as f:  f.seek(start)
        while remaining > 0:
            chunk = f.read(min(CHUNK_SIZE, remaining))
            if not chunk: break          # 文件被截短等意外，别死循环
            remaining -= len(chunk)
            yield chunk
      ★ yield 必须在 with 里面 —— 流式响应边发边读，句柄活到响应结束。

    TODO 写实现
    """
    # raise NotImplementedError
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
    """拼 Content-Disposition 头（RFC 5987 中文名）。复刻 7b FileResponse 的输出格式。

    规格（照抄 Starlette 的规则）：
      quoted = quote(filename)（urllib.parse；默认 safe='/' —— 文件名里不该有 '/'）
      quoted != filename → f"{disposition_type}; filename*=utf-8''{quoted}"
      否则               → f'{disposition_type}; filename="{filename}"'
    对拍基准（7b 实测的响应头，逐字符一致才算复刻成功）：
      attachment; filename*=utf-8''%E8%AF%B4%E6%98%8E.txt

    TODO 写实现
    """
    # raise NotImplementedError
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

    规格：
      ① file_size = file_path.stat().st_size
      ② 公共头（三种响应都带）：
           accept-ranges: bytes
           content-disposition: content_disposition(disposition_type, file_path.name)
      ③ try: rng = parse_range(range_header, file_size)
         except RangeNotSatisfiable:
             headers 再加 content-range = f"bytes */{file_size}"
             → return Response(status_code=416, headers=headers)（空 body）
             （★ Starlette 这版 416 写的是 `*/{size}`，少了 "bytes " 前缀；RFC 9110 的
               unsatisfied-range 是 "bytes */" + 总长 —— 我们写全，差异写注释）
      ④ rng is None → start, end, status = 0, file_size - 1, 200
         否则 → start, end = rng；status = 206；headers 加
                content-range = f"bytes {start}-{end}/{file_size}"
      ⑤ headers["content-length"] = str(end - start + 1)
         （空文件 → end = -1 → "0"，正好；206 只算这一段）
      ⑥ return StreamingResponse(
             iter_range(file_path, start, end),
             status_code=status,
             media_type=mime,        # → content-type
             headers=headers,
         )

    ⚠️ 刻意不做（写进注释）：If-Range / ETag / Last-Modified 协商（7b 的 FileResponse 带了，
    我们不跟 —— 那是缓存协商的另一课）；多段 multipart（Java 也只取第一段）。

    TODO 写实现
    """
    # raise NotImplementedError
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
