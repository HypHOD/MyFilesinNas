"""下载签名（AES/ECB/PKCS5Padding + hex）。

对应 Java core/util/ProxyDownloadUrlUtils.java。

/pd/ 代理下载是匿名链路：<video> 标签与 window.open 无法携带 zfile-token，
且代理回源按路径契约不查询用户根目录。链路上没有用户身份，权限只能编码进
URL：用密钥把 (storageId, 文件路径, 过期时间) 加密成 hex 附在 URL 上。
修改路径、storageId 或过期时间都会导致校验失败。这是漏洞 #821（构造任意路径
下载他人文件）的修复。

算法与 Java 一致：AES/ECB/PKCS5Padding，密文转 hex。两个易错点：

1. hutool 的 SymmetricCrypto(AES, key) 默认 ECB + PKCS5Padding、无 IV；
   PyCryptodome 的 AES.new(key, AES.MODE_ECB) 不做 padding，需自行调用
   Crypto.Util.Padding。
2. Java 的 PKCS5Padding 在 AES（16 字节块）下与 PKCS7 字节级一致，
   pad(data, AES.block_size) 与 Java 互兼容。

密钥存放在 system_config.rsaHexKey（历史命名，实际是 AES 密钥），32 个 hex 字符
= 16 字节 = AES-128。生成逻辑见 modules/config/service.py；本模块只接收 hex_key，
保持纯函数、便于测试。

签名内容为三段用 ':' 连接（pathAndName 为含文件名、含用户根的完整路径）：
    "storageId:pathAndName:{过期毫秒}"    私有空间（proxyPrivate=true，默认），默认 30 分钟
    "storageId:pathAndName:PERMANENT"     公开空间（proxyPrivate=false）的永久签名
"""

import logging
import time

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad

from app.core.path_utils import concat

log = logging.getLogger(__name__)

#: 永久签名第三段的标记字面量。对应 Java PERMANENT_SIGNATURE_MARKER。
PERMANENT_SIGNATURE_MARKER = "PERMANENT"

#: 默认签名有效期（秒）。对应 Java PROXY_DOWNLOAD_LINK_EFFECTIVE_SECOND。
PROXY_DOWNLOAD_LINK_EFFECTIVE_SECOND = 1800


def encrypt_hex(content: str, hex_key: str) -> str:
    """AES/ECB/PKCS5Padding 加密 → hex 字符串。

    对应 Java SymmetricCrypto.encryptHex。tests/test_sign.py 直接调用它伪造
    过期签名（正常 API 生成不出过期签名）。
    """
    key = bytes.fromhex(hex_key)
    cipher = AES.new(key,AES.MODE_ECB)
    return cipher.encrypt(pad(content.encode("utf-8"), AES.block_size)).hex()


def decrypt_hex(signature_hex: str, hex_key: str) -> str:
    """encrypt_hex 的逆：hex 签名 → 明文内容。

    对应 Java SymmetricCrypto.decryptStr。密钥错误、数据被篡改或非法 hex 会抛
    ValueError（块填充校验失败）；畸形签名本就无法解出，上层统一捕获为 False。
    """
    key = bytes.fromhex(hex_key)
    cipher = AES.new(key,AES.MODE_ECB)
    return unpad(cipher.decrypt(bytes.fromhex(signature_hex)),AES.block_size).decode("utf-8")


def generator_signature(
    storage_id: int, path_and_name: str, effective_second: int | None, hex_key: str
) -> str:
    """生成会过期的签名。对应 Java generatorSignature()。

    调用点：AbstractProxyTransferService._sign_download_url() 的 proxyPrivate=true
    分支；文件列表中每个文件项的 url 都经过这里。effective_second 为 None 或 < 1
    时使用默认值 PROXY_DOWNLOAD_LINK_EFFECTIVE_SECOND（1800 秒）。
    """
    if effective_second is None or effective_second < 1:
        effective_second = PROXY_DOWNLOAD_LINK_EFFECTIVE_SECOND
    expire_millis = int(time.time() * 1000) +effective_second *1000
    content = f"{storage_id}:{path_and_name}:{expire_millis}"
    return encrypt_hex(content,hex_key)


def generator_permanent_signature(storage_id: int, path_and_name: str, hex_key: str) -> str:
    """生成永久签名：第三段写 PERMANENT 而不是过期时间。

    调用点：_sign_download_url() 的 proxyPrivate=false 分支（公开空间）。
    对应 Java generatorPermanentSignature()：路径绑定照旧，只是不设过期时间。
    公开空间同样必须带签名，以保证修改 URL 路径仍会被拦截（#821 的完整修法）。
    """
    content = f"{storage_id}:{path_and_name}:{PERMANENT_SIGNATURE_MARKER}"
    return encrypt_hex(content,hex_key)


def valid_signature_expired(
    expected_storage_id: int,
    expected_path_and_name: str,
    signature: str | None,
    hex_key: str,
) -> bool:
    """校验签名，返回 True 表示有效。函数名中的 expired 沿自 Java。

    调用点：proxy_router 的 /pd/ 入口；返回 False 时抛 41002。

    解析规则：storageId 取第一个冒号前的内容，过期段取最后一个冒号后的内容，中间
    全部视为路径。不能使用 split(":") 或 maxsplit=2：文件名可以包含 ':'（macOS
    合法），例如 "1:/alice/电影:最终版.mp4:1738"；全切会破坏路径，maxsplit=2 会把
    过期段留在路径中。

    校验规则：
      - signature 为空 → False
      - storageId 必须与期望值一致
      - 路径两侧都经 concat 归一化后比较：URL 提取的路径没有前导 '/'，签名内容有，
        需要 concat 补平；重复 '/' 也一并归一（Java 原逻辑，不要改成裸 ==）
      - 第三段为 PERMANENT → True（跳过过期校验）；否则按毫秒时间戳判断
      - 整个解析过程用 try/except Exception 包住，任何异常一律 False：校验器是
        攻击者可直接触达的入口，畸形输入只能得到 False，不能返回 500
      - 失败分支照 Java 记录 warning 日志（signature/storageId/pathAndName/now），
        作为入侵探测信号
    """
    if not signature:
        return False

    now_millis = int(time.time()) *1000

    try:
        storage_id_str, rest = decrypt_hex(signature, hex_key).split(":", 1)
        path_and_name, expired = rest.rsplit(":", 1)

        if storage_id_str != str(expected_storage_id) or concat(path_and_name) != concat(expected_path_and_name):
            log.warning(
                "校验链接不匹配, signature: %s, storageId=%s, pathAndName=%s, expiredSecond=%s, now: %s",
                signature, storage_id_str, path_and_name, expired, now_millis,
            )
            return False
        if expired == PERMANENT_SIGNATURE_MARKER:
            return True
        if now_millis < int(expired):
            return True

        log.warning(
            "校验链接已过期, signature: %s, storageId=%s, pathAndName=%s, expiredSecond=%s, now: %s",
            signature, storage_id_str, path_and_name, expired, now_millis,
        )
    except Exception:
        log.error("校验签名链接异常, signature: %s, now: %s", signature, now_millis)
        return False
    return False