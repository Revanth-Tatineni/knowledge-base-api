import asyncio
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any
from urllib.parse import urlparse

import asyncpg
import pytest
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

import app.models  # registers every model on Base.metadata
from app.core.config import Settings
from app.db.base import Base
from app.db.session import create_engine
from app.main import create_app

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL", "postgresql+asyncpg://kb:kb@localhost:5432/kb_test"
)
TEST_REDIS_URL = os.getenv("TEST_REDIS_URL", "redis://localhost:6379/15")

PASSWORD = "correct-horse-battery"


async def _create_database_and_schema() -> None:
    parsed = urlparse(TEST_DATABASE_URL.replace("+asyncpg", ""))
    db_name = parsed.path.lstrip("/")
    admin = await asyncpg.connect(
        user=parsed.username,
        password=parsed.password,
        host=parsed.hostname,
        port=parsed.port or 5432,
        database="postgres",
    )
    try:
        exists = await admin.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", db_name)
        if not exists:
            await admin.execute(f'CREATE DATABASE "{db_name}"')
    finally:
        await admin.close()

    engine = create_engine(TEST_DATABASE_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()


@pytest.fixture(scope="session", autouse=True)
def _schema() -> None:
    # Runs in its own event loop so no async resource leaks across test loops.
    asyncio.run(_create_database_and_schema())


@pytest.fixture
def settings() -> Settings:
    return Settings(
        environment="test",
        database_url=TEST_DATABASE_URL,
        redis_url=TEST_REDIS_URL,
        log_level="WARNING",
    )


@pytest.fixture
async def app(settings: Settings) -> AsyncIterator[FastAPI]:
    application = create_app(settings)
    async with LifespanManager(application):
        tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
        async with application.state.engine.begin() as conn:
            await conn.execute(text(f"TRUNCATE {tables} CASCADE"))
        await application.state.redis.flushdb()
        yield application


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


RegisterAndLogin = Callable[..., Awaitable[dict[str, Any]]]


@pytest.fixture
def register_and_login(client: AsyncClient) -> RegisterAndLogin:
    async def _go(email: str = "alice@example.com", password: str = PASSWORD) -> dict[str, Any]:
        resp = await client.post(
            "/api/v1/auth/register", json={"email": email, "password": password}
        )
        assert resp.status_code == 201, resp.text
        resp = await client.post(
            "/api/v1/auth/login", data={"username": email, "password": password}
        )
        assert resp.status_code == 200, resp.text
        tokens: dict[str, Any] = resp.json()
        tokens["headers"] = {"Authorization": f"Bearer {tokens['access_token']}"}
        return tokens

    return _go


@pytest.fixture
async def auth_headers(register_and_login: RegisterAndLogin) -> dict[str, str]:
    tokens = await register_and_login()
    headers: dict[str, str] = tokens["headers"]
    return headers
