from pathlib import Path

from .config import CONFIG_PATH, VERSION, Settings
from .log import setup_logger

DATA_PATH = "sqlite:///data/data.db"
POSTERS_PATH = Path("data/posters")
VERSION_PATH = Path("config/version.info")

settings = Settings()

__all__ = [
    "CONFIG_PATH",
    "DATA_PATH",
    "POSTERS_PATH",
    "VERSION",
    "VERSION_PATH",
    "Settings",
    "settings",
    "setup_logger",
]
