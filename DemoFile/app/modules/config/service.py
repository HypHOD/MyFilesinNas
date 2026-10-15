import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.config import SystemConfig
from app.modules.config.schemas import SiteConfig


def get_site_config(db: Session) -> SiteConfig:
    """读全表，转成 SiteConfig。

    对应 SystemConfigService.getSystemConfig()（Java 那边还有一层缓存，我们不需要）。
    """
    rows = db.scalars(select(SystemConfig)).all()
    return SiteConfig.from_rows({row.name: row.value for row in rows})


def update_site_config(db: Session, config: SiteConfig) -> None:
    """部分更新：只写 config 里**非 None** 的字段。

    对应 SystemConfigService.updateSystemConfig()。

    Java 那段的核心是一行 `if (val != null)`。这个语义是 install() 能只传两个字段
    的前提，也是本步骤最容易写错的地方 —— 如果你实现成"整个 dict 覆写回表"，
    一次安装就会把其余 78 行配置洗成 null，站点当场报废。
    """
    rows = {row.name: row for row in db.scalars(select(SystemConfig)).all()}

    for name, value in config.model_dump(exclude_none=True).items():
        row = rows.get(name)            # name 不在表里：Java 的 update 也是影响 0 行
        if row is None:
            continue
        if isinstance(value, bool):
            new_value = "true" if value else "false"    # str(True) 会得到 "True"，和 Java 对不上
        else:
            new_value = str(value)
        if row.value != new_value:
            row.value = new_value

    db.commit()


def get_aes_hex_key_or_generate(db: Session) -> str:
    """读 system_config.rsaHexKey（AES 密钥，HEX）；为空则生成一个并写回 DB。

    对应 SystemConfigService.getAesHexKeyOrGenerate()（Java 186-202 行）。
    （名字叫 rsaHexKey 是 Java 的历史遗留 —— 存的是 AES 对称密钥。）

    用途：签名体系的地基。两个调用点：
      - base.AbstractProxyTransferService._sign_download_url()（生成签名，7a）
      - modules/storage/proxy_router.py 的 /pd/ 入口（校验签名，7b）

    规格：
      - select SystemConfig where name == "rsaHexKey"
      - 行存在且 value 非空 → 直接返回 value
      - value 为空 → 生成 16 字节随机密钥的 hex（secrets.token_hex(16) = 32 个字符；
        Java SecureUtil.generateKey(AES) 默认也是 128 位）→ 写回该行 + commit → 返回
      - 行不存在（正常不会，R__data.sql 已插）→ 新建 SystemConfig(name="rsaHexKey",
        value=key) 入库再返回 —— ★ 必须落库：不落库的话每次调用都生成新密钥，
        签了没法验，下载链路必挂（Java 在这条路上会直接 NPE，我们做得稳一点）

    差异：Java 有 AES_CACHE + DTO 缓存，我们每次读库（先正确后优化）—— 写进注释。

    TODO 写实现
    """
    # raise NotImplementedError
    row = db.scalar(select(SystemConfig).where(SystemConfig.name == "rsaHexKey"))

    if row is not None and row.value:
        return row.value

    key = secrets.token_hex(16)
    if row is not None:
        row.value = key
    else:
        db.add(SystemConfig(name="rsaHexKey", title="RSA 算法 HEX 格式密钥", value=key))
    db.commit()
    return key