from collections.abc import Iterator
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def init_engine(url: str) -> Engine:
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = create_engine(url, connect_args={"check_same_thread": False})

    @event.listens_for(_engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.close()

    _session_factory = sessionmaker(_engine, expire_on_commit=False)
    return _engine


def migrate(url: str) -> None:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")


def get_db() -> Iterator[Session]:
    assert _session_factory is not None, "init_engine() not called"
    with _session_factory() as session:
        yield session
