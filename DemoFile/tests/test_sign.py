"""步骤 7a 验收：AES 下载签名。**纯函数** —— 不碰 DB、不启 FastAPI（密钥直接传）。

    .venv/bin/python -m pytest tests/test_sign.py -v

签名方案的三条不变量（任何一条挂 = 权限隔离有洞）：
  1. 签名绑定了 (storageId, 路径) —— 改任何一个字符都必须失败
  2. 私有签名会过期 —— 过期时间出自密文内部，外部改不了
  3. 永久签名只跳过时间校验，**不跳过**路径校验
"""

import time

from app.core.sign import (
    PROXY_DOWNLOAD_LINK_EFFECTIVE_SECOND,
    decrypt_hex,
    encrypt_hex,
    generator_permanent_signature,
    generator_signature,
    valid_signature_expired,
)

# 固定的 16 字节密钥（32 hex 字符）。测试里不用随机密钥 —— 断言才能确定。
KEY = "00112233445566778899aabbccddeeff"
OTHER_KEY = "ffeeddccbbaa99887766554433221100"


def _now_ms() -> int:
    return int(time.time() * 1000)


def test_encrypt_decrypt_roundtrip() -> None:
    """加密再解密回原文（含中文和冒号 —— 冒号在 macOS 文件名里合法）。"""
    content = "1:/alice/电影:最终版.mp4:1735689600000"
    assert decrypt_hex(encrypt_hex(content, KEY), KEY) == content


def test_valid_signature_passes() -> None:
    sig = generator_signature(1, "/alice/sub/a.txt", 1800, KEY)
    assert valid_signature_expired(1, "/alice/sub/a.txt", sig, KEY) is True


def test_path_tampering_rejected() -> None:
    """★ 核心：拿一个合法签名，把路径改成别的文件 → 必须 False。"""
    sig = generator_signature(1, "/alice/sub/a.txt", 1800, KEY)
    assert valid_signature_expired(1, "/alice/sub/other.txt", sig, KEY) is False
    assert valid_signature_expired(1, "/bob/secret.txt", sig, KEY) is False


def test_storage_id_mismatch_rejected() -> None:
    """签名绑定存储源 id：签的是 1 号源，拿到 2 号源上校验 → False。"""
    sig = generator_signature(1, "/alice/a.txt", 1800, KEY)
    assert valid_signature_expired(2, "/alice/a.txt", sig, KEY) is False


def test_leading_slash_normalized() -> None:
    """URL 提取的路径没有前导 '/'，签名内容有 —— concat 归一化后必须相等。

    （"/alice//a.txt" 那道是合并重复 '/' 的规范化，同一个 concat 顺手管的。）
    """
    sig = generator_signature(1, "/alice/a.txt", 1800, KEY)
    assert valid_signature_expired(1, "alice/a.txt", sig, KEY) is True
    assert valid_signature_expired(1, "/alice//a.txt", sig, KEY) is True


def test_path_with_colon_valid() -> None:
    """文件名含 ':' 也要能通过 —— 解析必须用 split(":", 2)（Java 的 split 在这里会挂）。"""
    sig = generator_signature(1, "/alice/电影:最终版.mp4", 1800, KEY)
    assert valid_signature_expired(1, "/alice/电影:最终版.mp4", sig, KEY) is True


def test_expired_signature_rejected() -> None:
    """过期时间在密文里，正常 API 生成不出过期签名 —— 用 encrypt_hex 手搓一个过去的毫秒。"""
    past = _now_ms() - 1000
    sig = encrypt_hex(f"1:/alice/a.txt:{past}", KEY)
    assert valid_signature_expired(1, "/alice/a.txt", sig, KEY) is False


def test_permanent_signature_never_expires() -> None:
    """永久签名不校验时间，但路径绑定依然生效（不变量 3）。"""
    sig = generator_permanent_signature(1, "/alice/a.txt", KEY)
    assert valid_signature_expired(1, "/alice/a.txt", sig, KEY) is True
    assert valid_signature_expired(1, "/alice/b.txt", sig, KEY) is False


def test_default_effective_second() -> None:
    """effective_second 传 None / 0 / 负数 → 落回默认 1800 秒（Java: 为空或 <1 走默认）。

    判据：解密出第三段，剩余毫秒必须在 (0, 1800s] 区间内。
    """
    for bad in (None, 0, -5):
        sig = generator_signature(1, "/alice/a.txt", bad, KEY)
        _, _, expire = decrypt_hex(sig, KEY).split(":", 2)
        remaining_ms = int(expire) - _now_ms()
        assert 0 < remaining_ms <= PROXY_DOWNLOAD_LINK_EFFECTIVE_SECOND * 1000


def test_garbage_signature_rejected() -> None:
    """畸形输入只许得到 False —— 校验器是攻击者能直接触达的入口，不许 500。"""
    assert valid_signature_expired(1, "/alice/a.txt", None, KEY) is False
    assert valid_signature_expired(1, "/alice/a.txt", "", KEY) is False
    assert valid_signature_expired(1, "/alice/a.txt", "not-a-hex", KEY) is False
    assert valid_signature_expired(1, "/alice/a.txt", "abcdef", KEY) is False


def test_wrong_key_rejected() -> None:
    """换个密钥签的签名，用本系统的密钥校验 → False。"""
    sig = generator_signature(1, "/alice/a.txt", 1800, KEY)
    assert valid_signature_expired(1, "/alice/a.txt", sig, OTHER_KEY) is False
