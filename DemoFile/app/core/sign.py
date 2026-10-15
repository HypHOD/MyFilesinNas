"""下载签名（AES/ECB/PKCS5Padding + hex）。对应 Java core/util/ProxyDownloadUrlUtils.java。

【为什么要有签名】
    /pd/ 代理下载是**匿名链路**：<video> 标签、window.open 下载都带不了 zfile-token；
    而且按路径契约，代理回源绝不查用户根目录（步骤 4 的伏笔）。既然链路上没有"你是谁"，
    权限就只能编码进 URL 本身 —— 签名 = 用密钥把 (storageId, 文件路径, 过期时间)
    加密成一串 hex 附在 URL 上：
        改路径          → 比对失败
        改 storageId    → 比对失败
        过期            → 时间比对失败
    这是漏洞 #821（构造任意路径就能下载别人的文件）的修复：从密码学层面堵住。

【算法】照抄 Java：AES/ECB/PKCS5Padding，密文转 hex。
    ⚠️ 计划点名"自己确认清楚"的两个参数坑：
      1. hutool `new SymmetricCrypto(SymmetricAlgorithm.AES, key)` 默认是 **ECB + PKCS5Padding、
         无 IV**；而 PyCryptodome 的 AES.new(key, AES.MODE_ECB) **不做任何 padding** ——
         pad/unpad 要自己来（Crypto.Util.Padding）。
      2. Java 的 PKCS5Padding 在 AES（块长 16 字节）下与 PKCS7 字节级一致
         （PKCS5 名义上只定义 8 字节块，Java 的实现直接复用了 PKCS7）。所以
         pad(data, AES.block_size) 与 Java 互兼容。

【密钥】system_config.rsaHexKey（名字是历史遗留，实际存的就是 AES 密钥），32 个 hex 字符
    = 16 字节 = AES-128。Java 的生成+缓存逻辑见 getAesHexKeyOrGenerate()；
    Python 侧生成在 modules/config/service.py，本模块只接收 hex_key 参数（纯函数、好测）。

【签名内容格式】三段用 ':' 连接（pathAndName 是含文件名、含用户根的完整路径）：
    "storageId:pathAndName:{过期毫秒}"   私有空间（proxyPrivate=true，默认），默认 30 分钟
    "storageId:pathAndName:PERMANENT"    公开空间（proxyPrivate=false）的永久签名
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

    被本模块的 generator_signature / generator_permanent_signature 调用；
    tests/test_sign.py 也直接用它伪造"已过期"的签名（正常 API 生成不出过期签名）。
    对应 Java SymmetricCrypto.encryptHex。

    规格：
      - key = bytes.fromhex(hex_key)；cipher = AES.new(key, AES.MODE_ECB)（ECB 无 IV）
      - content.encode("utf-8") → pad(data, AES.block_size) → cipher.encrypt → .hex()

    TODO 写实现
    """
    # raise NotImplementedError
    key = bytes.fromhex(hex_key)
    cipher = AES.new(key,AES.MODE_ECB)
    return cipher.encrypt(pad(content.encode("utf-8"), AES.block_size)).hex()


def decrypt_hex(signature_hex: str, hex_key: str) -> str:
    """encrypt_hex 的逆：hex 签名 → 明文内容。

    被 valid_signature_expired 调用。对应 Java SymmetricCrypto.decryptStr。
    ⚠️ 密钥不对 / 数据被篡改 / 不是合法 hex → 抛 ValueError（块填充校验失败）。
    这是**预期行为**：畸形签名就是应该解不出来，上层统一 catch 成 False。

    规格：bytes.fromhex → AES.new(key, AES.MODE_ECB).decrypt → unpad(..., AES.block_size)
          → decode("utf-8")

    TODO 写实现
    """
    # raise NotImplementedError
    key = bytes.fromhex(hex_key)
    cipher = AES.new(key,AES.MODE_ECB)
    return unpad(cipher.decrypt(bytes.fromhex(signature_hex)),AES.block_size).decode("utf-8")


def generator_signature(
    storage_id: int, path_and_name: str, effective_second: int | None, hex_key: str
) -> str:
    """生成**会过期**的签名。对应 Java generatorSignature()。

    调用点：base.AbstractProxyTransferService._sign_download_url() 的 proxyPrivate=true 分支
    —— 文件列表里每个文件项的 url 都经过它。

    规格（Java 54-65 行）：
      - effective_second 为 None 或 < 1 → PROXY_DOWNLOAD_LINK_EFFECTIVE_SECOND（1800 秒）
      - 过期毫秒 = int(time.time() * 1000) + effective_second * 1000
        （Java 是 DateUtil.offsetSecond(now, second).getTime()，同一时刻的毫秒时间戳）
      - content = f"{storage_id}:{path_and_name}:{过期毫秒}" → encrypt_hex(content, hex_key)

    TODO 写实现
    """
    # raise NotImplementedError
    if effective_second is None or effective_second < 1:
        effective_second = PROXY_DOWNLOAD_LINK_EFFECTIVE_SECOND
    expire_millis = int(time.time() * 1000) +effective_second *1000
    content = f"{storage_id}:{path_and_name}:{expire_millis}"
    return encrypt_hex(content,hex_key)


def generator_permanent_signature(storage_id: int, path_and_name: str, hex_key: str) -> str:
    """生成**永久**签名：第三段写 PERMANENT 而不是过期时间。

    调用点：_sign_download_url() 的 proxyPrivate=false 分支（公开空间）。
    对应 Java generatorPermanentSignature()：路径绑定照旧，只是不再放过期时间 ——
    即使公开空间也必须带签名，这样"改 URL 路径"依然被拦（#821 的完整修法）。

    规格：content = f"{storage_id}:{path_and_name}:{PERMANENT_SIGNATURE_MARKER}"
          → encrypt_hex(content, hex_key)

    TODO 写实现
    """
    # raise NotImplementedError
    content = f"{storage_id}:{path_and_name}:{PERMANENT_SIGNATURE_MARKER}"
    return encrypt_hex(content,hex_key)


def valid_signature_expired(
    expected_storage_id: int,
    expected_path_and_name: str,
    signature: str | None,
    hex_key: str,
) -> bool:
    """校验签名。返回 True = **有效**（名字带 expired 是照抄 Java 的歧义，别被骗）。

    调用点：proxy_router 的 /pd/ 入口（步骤 7b）—— 返回 False 就抛 41002。

    规格（照 Java 88-139 行）：
      - signature 为空（None / ""）→ False
      - 解密后解析（★ 两端各切一刀）：
            storage_id_str, rest = 明文.split(":", 1)
            path_and_name, expired = rest.rsplit(":", 1)
        为什么不能像 Java 那样全切、也不能 maxsplit=2：文件名含 ':' 时（macOS 合法），
        内容会变成 "1:/alice/电影:最终版.mp4:1738" —— 一共 3 个冒号。全切会把路径切碎；
        maxsplit=2 也错（切在前两个冒号，把过期段留在路径里）。只有"第一个冒号前 = storageId、
        最后一个冒号后 = 过期段、中间全算路径"才是对的。tests 里 test_path_with_colon_valid
        钉的就是这个行为（这条规格第一版写错了，就是被那条测试抓出来的）。
        切不出两段 → 交给下面统一 catch → False
      - 存储源比对：str(expected_storage_id) == storage_id_str
      - 路径比对：concat(path_and_name) == concat(expected_path_and_name)
        ★ 两侧都要 concat 归一化再比！URL 里提取的路径没有前导 '/'，而签名内容里有，
          靠 concat 补平；重复 '/' 也一并归一 —— 这是 Java 的原逻辑，别改成裸 ==
      - expired == PERMANENT_SIGNATURE_MARKER → True（永久签名跳过过期校验）
      - 否则 int(expired) > 当前毫秒（int(time.time() * 1000)）→ True，否则 False
      - 整个解析过程用 try/except Exception 包住 → 任何异常一律 False
        （校验器是攻击者能直接触达的入口：畸形输入只许得到 False，不许 500）
      - 失败各分支照 Java 打 log.warning（"校验链接不匹配 / 已过期"，带上
        signature/storageId/pathAndName/now）—— 这类日志是入侵探测的信号

    TODO 写实现
    """
    # raise NotImplementedError
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