"""步骤 7c 验收：手写 HTTP Range。**纯函数** —— 不碰 DB、不启 FastAPI。

    /opt/anaconda3/envs/py310/bin/python -m pytest tests/test_range.py -v

三条要钉住的不变量：
  1. 协议四件套：请求三形态（闭区间 / 开区间 / suffix）→ 可满足回 206 + Content-Range、
     不可满足回 416、每个响应都带 Accept-Ranges
  2. 两条宽容规则（RFC 9110 §14.2）：end 超尾 → 截断到 size-1，不算错；
     畸形 → 忽略请求头回 200 全文，也不算错
     ★ 畸形回 200 是刻意选择：Starlette 回 400、Java writeFile 直接 500 —— 我们跟 RFC
  3. 分块 I/O：迭代器按 CHUNK_SIZE 切、空区间连文件都不开、响应体与源文件逐字节一致
"""

import asyncio
from pathlib import Path

import pytest

from app.core.stream import (
    CHUNK_SIZE,
    RangeNotSatisfiable,
    build_file_response,
    content_disposition,
    iter_range,
    parse_range,
)

SIZE = 1024
DATA = bytes(range(256)) * 4  # 1024 字节；每个位置的值可预测 → 切片断言好写

MIME = "application/octet-stream"
DISPOSITION = "attachment"


@pytest.fixture()
def sample(tmp_path: Path) -> Path:
    f = tmp_path / "sample.bin"
    f.write_bytes(DATA)
    return f


def _body(response) -> bytes:
    """把 StreamingResponse 的异步 body 排干 —— 拿到的就是真会发出去的字节。"""

    async def _drain() -> bytes:
        return b"".join([chunk async for chunk in response.body_iterator])

    return asyncio.run(_drain())


# ── parse_range：请求头 → 闭区间 ──────────────────────────────────────


def test_parse_range_missing_or_blank() -> None:
    """没带 Range / 空串 / 纯空白 → None（调用方回 200 全文）。"""
    assert parse_range(None, SIZE) is None
    assert parse_range("", SIZE) is None
    assert parse_range("   ", SIZE) is None


def test_parse_range_closed_interval() -> None:
    """bytes=0-4 是闭区间：[0, 4] 共 5 字节。"""
    assert parse_range("bytes=0-4", SIZE) == (0, 4)


def test_parse_range_open_ended() -> None:
    """bytes=1000- → 从 1000 到文件尾。"""
    assert parse_range("bytes=1000-", SIZE) == (1000, SIZE - 1)


def test_parse_range_suffix() -> None:
    """bytes=-10 → 最后 10 字节（★ 数字含义和 'start-' 那两种相反）。"""
    assert parse_range("bytes=-10", SIZE) == (SIZE - 10, SIZE - 1)


def test_parse_range_suffix_bigger_than_file() -> None:
    """suffix ≥ 文件大小 → 整个文件（不是错误）。"""
    assert parse_range("bytes=-5000", SIZE) == (0, SIZE - 1)


def test_parse_range_end_clamped_to_size() -> None:
    """★ 宽容规则一：end 超尾 → 截断到 size-1，不是错误。"""
    assert parse_range("bytes=1000-99999", SIZE) == (1000, SIZE - 1)


def test_parse_range_whitespace_tolerated() -> None:
    """'bytes= 0-4' 这种带空格的写法容忍（去前缀后分段再 strip）。"""
    assert parse_range("bytes= 0-4", SIZE) == (0, 4)


def test_parse_range_multi_takes_first() -> None:
    """多段只取第一段 —— 跟 Java writeFile 的集合取首，不做 multipart/byteranges。"""
    assert parse_range("bytes=0-4,10-19", SIZE) == (0, 4)


@pytest.mark.parametrize(
    "header",
    [
        "0-4",  # 没有 bytes= 前缀
        "bytes=abc",  # 不是数字
        "bytes=10-abc",  # end 不是数字
        "bytes=",  # 前缀后面是空的
        "bytes=5-2",  # 倒置区间（RFC：整组无效 → 忽略）
        "bytes=+5-10",  # 带符号数字
        "BYTES=0-4",  # 前缀大小写敏感（照 Java）
    ],
)
def test_parse_range_malformed_ignored(header: str) -> None:
    """★ 宽容规则二：畸形 → None → 200 全文。"""
    assert parse_range(header, SIZE) is None


@pytest.mark.parametrize("header", ["bytes=1024-", "bytes=2000-3000"])
def test_parse_range_unsatisfiable_raises(header: str) -> None:
    """★ start ≥ 文件大小 → 416 —— Java 在这会算出负数 Content-Length，我们刻意偏离。"""
    with pytest.raises(RangeNotSatisfiable) as exc:
        parse_range(header, SIZE)
    assert exc.value.file_size == SIZE


def test_parse_range_empty_file_raises() -> None:
    """空文件：任何 Range 都不可满足 → 416（响应头会拼 bytes */0）。"""
    with pytest.raises(RangeNotSatisfiable):
        parse_range("bytes=0-", 0)


# ── iter_range：闭区间 → 分块字节流 ───────────────────────────────────


def test_iter_range_middle_slice(sample: Path) -> None:
    assert b"".join(iter_range(sample, 10, 19)) == DATA[10:20]


def test_iter_range_whole_file(sample: Path) -> None:
    assert b"".join(iter_range(sample, 0, SIZE - 1)) == DATA


def test_iter_range_chunks(tmp_path: Path) -> None:
    """大文件按 CHUNK_SIZE 分块，没有一块超过它（文件不进内存的保证）。"""
    size = CHUNK_SIZE * 2 + 123
    content = (bytes(range(256)) * (size // 256 + 1))[:size]
    big = tmp_path / "big.bin"
    big.write_bytes(content)

    chunks = list(iter_range(big, 0, size - 1))
    assert [len(c) for c in chunks] == [CHUNK_SIZE, CHUNK_SIZE, 123]
    assert b"".join(chunks) == content


def test_iter_range_empty_returns_without_opening_file(tmp_path: Path) -> None:
    """start > end → 直接空返回（空文件 0,-1 走这条），连文件都不用打开。"""
    missing = tmp_path / "does-not-exist.bin"
    assert list(iter_range(missing, 5, 2)) == []
    assert list(iter_range(missing, 0, -1)) == []


# ── content_disposition：RFC 5987 中文文件名 ──────────────────────────


@pytest.mark.parametrize(
    ("disposition_type", "filename", "expected"),
    [
        ("attachment", "a.txt", 'attachment; filename="a.txt"'),
        (
            "attachment",
            "说明.txt",
            "attachment; filename*=utf-8''%E8%AF%B4%E6%98%8E.txt",
        ),
        ("inline", "说明.txt", "inline; filename*=utf-8''%E8%AF%B4%E6%98%8E.txt"),
        ("attachment", "a b.txt", "attachment; filename*=utf-8''a%20b.txt"),
    ],
)
def test_content_disposition(
    disposition_type: str, filename: str, expected: str
) -> None:
    """纯 ASCII → 引号式；含非 ASCII 或空格 → RFC 5987 式。

    第二条就是 7b 实测的响应头 —— 逐字符对拍基准。
    """
    assert content_disposition(disposition_type, filename) == expected


# ── build_file_response：200 / 206 / 416 三态组装 ─────────────────────


def test_build_full_200(sample: Path) -> None:
    response = build_file_response(sample, mime=MIME, disposition_type=DISPOSITION)
    assert response.status_code == 200
    assert response.headers["content-length"] == str(SIZE)
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-disposition"] == 'attachment; filename="sample.bin"'
    assert response.headers["content-type"] == MIME
    assert "content-range" not in response.headers
    assert _body(response) == DATA


def test_build_range_206(sample: Path) -> None:
    response = build_file_response(
        sample, mime=MIME, disposition_type=DISPOSITION, range_header="bytes=10-19"
    )
    assert response.status_code == 206
    assert response.headers["content-range"] == f"bytes 10-19/{SIZE}"
    assert response.headers["content-length"] == "10"  # 只算这一段
    assert response.headers["accept-ranges"] == "bytes"
    assert _body(response) == DATA[10:20]


def test_build_range_206_open_ended(sample: Path) -> None:
    response = build_file_response(
        sample, mime=MIME, disposition_type=DISPOSITION, range_header="bytes=1000-"
    )
    assert response.status_code == 206
    assert response.headers["content-range"] == f"bytes 1000-{SIZE - 1}/{SIZE}"
    assert response.headers["content-length"] == str(SIZE - 1000)


def test_build_unsatisfiable_416(sample: Path) -> None:
    """★ 416 的 Content-Range 写 RFC 完整的 'bytes */size'。

    （7b 实测 Starlette FileResponse 写的是 `*/80` —— 少了 'bytes ' 前缀、且不带
    accept-ranges / content-disposition；我们三种响应都带公共头。）
    """
    response = build_file_response(
        sample, mime=MIME, disposition_type=DISPOSITION, range_header="bytes=5000-"
    )
    assert response.status_code == 416
    assert response.headers["content-range"] == f"bytes */{SIZE}"
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-disposition"] == 'attachment; filename="sample.bin"'
    assert response.body == b""


def test_build_malformed_treated_as_full_200(sample: Path) -> None:
    """畸形 Range → 忽略 → 200 全文（7b 实测是 400，改成 RFC 行为）。"""
    response = build_file_response(
        sample, mime=MIME, disposition_type=DISPOSITION, range_header="banana"
    )
    assert response.status_code == 200
    assert response.headers["content-length"] == str(SIZE)


def test_build_empty_file_no_range(tmp_path: Path) -> None:
    """空文件无 Range → 200 + content-length 0（end = -1 的算术正好落在 '0'）。"""
    empty = tmp_path / "empty.bin"
    empty.write_bytes(b"")
    response = build_file_response(empty, mime=MIME, disposition_type=DISPOSITION)
    assert response.status_code == 200
    assert response.headers["content-length"] == "0"
    assert _body(response) == b""


def test_build_empty_file_with_range_416(tmp_path: Path) -> None:
    empty = tmp_path / "empty.bin"
    empty.write_bytes(b"")
    response = build_file_response(
        empty, mime=MIME, disposition_type=DISPOSITION, range_header="bytes=0-"
    )
    assert response.status_code == 416
    assert response.headers["content-range"] == "bytes */0"
