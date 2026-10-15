import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr, ValidationError

from app.core.config import Settings


async def test_liveness(client: AsyncClient) -> None:
    resp = await client.get("/health/live")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_readiness_ok(client: AsyncClient) -> None:
    resp = await client.get("/health/ready")
    assert resp.status_code == 200
    assert resp.json()["checks"] == {"database": "ok", "redis": "ok"}


async def test_readiness_degraded_when_dependency_down(
    client: AsyncClient, app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def boom() -> None:
        raise ConnectionError("redis down")

    monkeypatch.setattr(app.state.redis, "ping", boom)
    resp = await client.get("/health/ready")
    assert resp.status_code == 503
    assert resp.json() == {
        "status": "degraded",
        "checks": {"database": "ok", "redis": "unavailable"},
    }


async def test_request_id_is_echoed_and_generated(client: AsyncClient) -> None:
    resp = await client.get("/health/live", headers={"X-Request-ID": "abc123"})
    assert resp.headers["X-Request-ID"] == "abc123"
    generated = (await client.get("/health/live")).headers["X-Request-ID"]
    assert len(generated) == 32


async def test_error_envelope_on_unknown_route(client: AsyncClient) -> None:
    resp = await client.get("/nope", headers={"X-Request-ID": "req-1"})
    assert resp.status_code == 404
    assert resp.json() == {
        "error": {"code": "http_error", "message": "Not Found", "request_id": "req-1"}
    }


async def test_unhandled_exception_returns_500_envelope(app: FastAPI) -> None:
    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("kaboom")

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.get("/boom")
    assert resp.status_code == 500
    assert resp.json()["error"]["code"] == "internal_error"
    assert "kaboom" not in resp.text


def test_production_requires_real_secret() -> None:
    with pytest.raises(ValidationError):
        Settings(environment="production")
    with pytest.raises(ValidationError):
        Settings(environment="production", jwt_secret_key=SecretStr("too-short"))
    Settings(environment="production", jwt_secret_key=SecretStr("x" * 32))
