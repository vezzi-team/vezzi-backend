"""Общие фикстуры тестов.

Тесты работают с настоящим PostgreSQL. Перед запуском создаётся чистая база
vezzi_test и применяются миграции (так заодно проверяются и они). Каждый тест
выполняется в транзакции, которая в конце откатывается.
"""

import os
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://vezzi:vezzi@localhost:5432/vezzi_test"
)
os.environ.update(
    {
        "ENVIRONMENT": "test",
        "DATABASE_URL": TEST_DATABASE_URL,
        "JWT_SECRET_KEY": "test-secret-key-that-is-long-enough-for-hs256",
        "ROUTING_PROVIDER": "fake",
        "AUTH_RATE_LIMIT_PER_MINUTE": "1000",
        "LOG_LEVEL": "WARNING",
    }
)

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.catalog_import.publisher import ImportReport, publish_catalog
from app.core.rate_limit import RateLimit
from app.core.security import hash_password
from app.db.session import get_session
from app.demo.catalog import build_demo_catalog
from app.main import app
from app.models import User, UserRole
from app.routing import get_routing_provider
from app.routing.fake import FakeRoutingProvider

ROOT = Path(__file__).resolve().parents[1]
PASSWORD = "correct-horse-42"


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    url = make_url(TEST_DATABASE_URL)
    server = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with server.connect() as connection:
        connection.execute(text(f'DROP DATABASE IF EXISTS "{url.database}" WITH (FORCE)'))
        connection.execute(text(f'CREATE DATABASE "{url.database}"'))
    server.dispose()

    config = Config(ROOT / "alembic.ini")
    config.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    command.upgrade(config, "head")

    test_engine = create_engine(TEST_DATABASE_URL)
    yield test_engine
    test_engine.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    connection = engine.connect()
    transaction = connection.begin()
    db_session = Session(
        bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
    )
    yield db_session
    db_session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def client(session: Session) -> Iterator[TestClient]:
    def request_session() -> Session:
        # В приложении у каждого запроса своя сессия: видим базу, а не кэш прошлого запроса.
        session.expire_all()
        return session

    app.dependency_overrides[get_session] = request_session
    app.dependency_overrides[get_routing_provider] = FakeRoutingProvider
    RateLimit.reset_all()
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def register(client: TestClient) -> Callable[[str], dict[str, str]]:
    """Регистрирует пользователя и возвращает заголовки с его access-токеном."""

    def _register(email: str) -> dict[str, str]:
        response = client.post("/api/v1/auth/register", json={"email": email, "password": PASSWORD})
        assert response.status_code == 201, response.text
        return {"Authorization": f"Bearer {response.json()['tokens']['access_token']}"}

    return _register


@pytest.fixture
def user_headers(register: Callable[[str], dict[str, str]]) -> dict[str, str]:
    return register("alice@example.com")


@pytest.fixture
def admin_headers(client: TestClient, session: Session) -> dict[str, str]:
    session.add(
        User(email="admin@example.com", password_hash=hash_password(PASSWORD), role=UserRole.ADMIN)
    )
    session.commit()
    response = client.post(
        "/api/v1/auth/login", json={"email": "admin@example.com", "password": PASSWORD}
    )
    return {"Authorization": f"Bearer {response.json()['tokens']['access_token']}"}


@pytest.fixture
def demo_catalog(session: Session) -> ImportReport:
    now = datetime.now(UTC)
    return publish_catalog(
        session, build_demo_catalog(now), source_name="demo", file_sha256="demo", now=now
    )
