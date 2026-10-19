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
    """部分更新：只写入 config 中非 None 的字段。

    对应 SystemConfigService.updateSystemConfig()，语义等价于 Java 的
    `if (val != null)`，也是 install() 只传部分字段的前提。必须保持部分更新：
    整体覆写会把未传的配置行写成 null。
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
    """读取 system_config.rsaHexKey（AES 密钥，HEX），为空时生成并写回。

    对应 SystemConfigService.getAesHexKeyOrGenerate()。字段名中的 rsa 是 Java 的
    历史遗留，实际存储的是 AES 对称密钥。

    签名生成（_sign_download_url）和校验（/pd/ 入口）都从这里取密钥。密钥为空时
    生成 16 字节随机值的 hex（32 个字符，对应 Java 的 128 位密钥）并写回数据库；
    行不存在时新建后落库。必须持久化，否则每次调用都会生成新密钥，已签发的下载
    地址全部失效。Java 有缓存，这里每次读库，优先保证正确性。
    """
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