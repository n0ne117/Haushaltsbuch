import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import db as app_db
from app.main import create_app
from app.models import Account, Category, Tag


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with TestClient(create_app()) as c:
        yield c


@pytest.fixture
def db(client):
    gen = app_db.get_db()
    session = next(gen)
    yield session
    gen.close()


@pytest.fixture
def seed(db):
    """Lookup helpers for the seeded rows (by name)."""

    class Seed:
        def account(self, name: str) -> Account:
            return db.scalars(select(Account).where(Account.name == name)).one()

        def category(self, name: str, type: str | None = None) -> Category:
            stmt = select(Category).where(Category.name == name)
            if type:
                stmt = stmt.where(Category.type == type)
            return db.scalars(stmt).one()

        def tag(self, name: str) -> Tag:
            return db.scalars(select(Tag).where(Tag.name == name)).one()

    return Seed()
