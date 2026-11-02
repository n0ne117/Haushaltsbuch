"""Nightly SQLite backups (spec §12).

At 03:00 Europe/Vienna a consistent copy is written with SQLite's online backup API to
<DATA_DIR>/backups/haushaltsbuch-YYYY-MM-DD.db; the newest BACKUP_KEEP_DAYS files are kept.
Restic/Backrest on the host backs up that folder, never the live database.
"""

import asyncio
import logging
import os
import sqlite3
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

from app import config
from app.config import TZ

log = logging.getLogger(__name__)

BACKUP_TIME = time(3, 0)
PREFIX, SUFFIX = "haushaltsbuch-", ".db"

_last_error: str | None = None


def backup_dir() -> Path:
    return config.data_dir() / "backups"


def keep_days() -> int:
    value = os.environ.get("BACKUP_KEEP_DAYS", "14")
    return max(1, int(value)) if value.isdigit() else 14


def enabled() -> bool:
    return os.environ.get("BACKUP_ENABLED", "true").lower() != "false"


def _db_path() -> Path:
    return Path(config.database_url().removeprefix("sqlite:///"))


def backups() -> list[Path]:
    """Backup files, newest first (the date in the name sorts correctly)."""
    return sorted(backup_dir().glob(f"{PREFIX}????-??-??{SUFFIX}"), reverse=True)


def _file_date(path: Path) -> date:
    return date.fromisoformat(path.name.removeprefix(PREFIX).removesuffix(SUFFIX))


def run_backup(today: date | None = None) -> Path:
    today = today or datetime.now(TZ).date()
    target_dir = backup_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{PREFIX}{today.isoformat()}{SUFFIX}"
    tmp = target.with_name(target.name + ".tmp")

    src = sqlite3.connect(_db_path())
    dst = sqlite3.connect(tmp)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    os.replace(tmp, target)  # atomic: restic never sees a half-written file

    for old in backups()[keep_days():]:
        old.unlink()
    return target


def status() -> dict:
    files = backups()
    latest = files[0] if files else None
    return {
        "enabled": enabled(),
        "last_time": datetime.fromtimestamp(latest.stat().st_mtime, TZ) if latest else None,
        "last_file": latest.name if latest else None,
        "count": len(files),
        "keep": keep_days(),
        "error": _last_error,
    }


def seconds_until_next_run(now: datetime) -> float:
    target = datetime.combine(now.date(), BACKUP_TIME, TZ)
    if target <= now:
        target = datetime.combine(now.date() + timedelta(days=1), BACKUP_TIME, TZ)
    # Subtract in UTC: aware datetimes sharing a ZoneInfo subtract by wall clock and ignore DST changes.
    return (target.astimezone(UTC) - now.astimezone(UTC)).total_seconds()


def needs_catch_up(today: date) -> bool:
    """True if a nightly run was missed (e.g. the container was down at 03:00)."""
    files = backups()
    return not files or _file_date(files[0]) < today - timedelta(days=1)


async def _run_once() -> None:
    global _last_error
    try:
        path = await asyncio.to_thread(run_backup)
        _last_error = None
        log.info("Backup written: %s", path)
    except Exception as e:  # keep the scheduler alive; show the error in Einstellungen
        _last_error = f"{datetime.now(TZ):%d.%m.%Y %H:%M}: {e}"
        log.exception("Backup failed")


async def scheduler() -> None:
    if needs_catch_up(datetime.now(TZ).date()):
        await _run_once()
    while True:
        await asyncio.sleep(seconds_until_next_run(datetime.now(TZ)))
        await _run_once()
