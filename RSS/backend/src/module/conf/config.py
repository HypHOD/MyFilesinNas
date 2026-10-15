import json
import logging
from pathlib import Path

from module.models.config import Config

logger = logging.getLogger(__name__)

VERSION = "DEV_VERSION"

CONFIG_ROOT = Path("config")
CONFIG_PATH = (
    CONFIG_ROOT / "config_dev.json"
    if VERSION == "DEV_VERSION"
    else CONFIG_ROOT / "config.json"
).resolve()


class Settings(Config):
    """运行时配置单例

    构造时从 ``CONFIG_PATH`` 加载（不存在则把默认值落盘）；``load()`` 从磁盘
    重新读取并替换全部字段，是配置热重载的底层动作（入口见
    ``AppContext.reload_settings``）。全局实例见 ``module.conf.settings``。
    """

    def __init__(self):
        super().__init__()
        if CONFIG_PATH.exists():
            self.load()
        else:
            self.save()

    def load(self) -> None:
        """从 CONFIG_PATH 读取并校验，替换实例的全部字段值。"""
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            config = json.load(f)
        config_obj = Config.model_validate(config)
        self.__dict__.update(config_obj.__dict__)
        logger.debug("Config loaded")

    def save(self, config_dict: dict | None = None) -> None:
        """把配置写入 CONFIG_PATH；不传 dict 时保存当前状态。"""
        if config_dict is None:
            config_dict = self.model_dump()
        CONFIG_ROOT.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config_dict, f, indent=4, ensure_ascii=False)
        logger.debug("Config saved")
