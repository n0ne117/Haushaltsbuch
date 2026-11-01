import os
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Vienna")


def data_dir() -> Path:
    return Path(os.environ.get("DATA_DIR", "/data"))


def database_url() -> str:
    return os.environ.get("DATABASE_URL") or f"sqlite:///{data_dir() / 'haushaltsbuch.db'}"
