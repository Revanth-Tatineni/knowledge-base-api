from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from redis.exceptions import ConnectionError as RedisConnectionError

from app.core.rate_limit import RateLimiter

LOGIN = "/api/v1/auth/login"


async def test_login_is_limited_per_ip(client: AsyncClient) -> None:
    creds = {"username": "nobody@example.com", "password": "whatever-123"}
    for remaining in range(4, -1, -1):
        resp = await client.post(LOGIN, data=creds)
        assert resp.status_code == 401
        assert resp.headers["X-RateLimit-Remaining"] == str(remaining)

    blocked = await client.post(LOGIN, data=creds)
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "rate_limited"
    assert 0 < int(blocked.headers["Retry-After"]) <= 60


async def test_authenticated_routes_limited_per_user(
    client: AsyncClient, app: FastAPI, auth_headers: dict[str, str]
) -> None:
    app.state.settings.rate_limit_default = 3
    for _ in range(3):
        assert (await client.get("/api/v1/notes", headers=auth_headers)).status_code == 200
    assert (await client.get("/api/v1/notes", headers=auth_headers)).status_code == 429


async def test_rate_limiter_counts_within_a_window(app: FastAPI) -> None:
    limiter = RateLimiter(app.state.redis)
    results = [await limiter.hit("t", "id", limit=2, window=60) for _ in range(3)]
    assert [r.allowed for r in results] == [True, True, False]
    assert [r.remaining for r in results] == [1, 0, 0]
    keys = await app.state.redis.keys("rl:t:id:*")
    assert len(keys) == 1
    assert 0 < await app.state.redis.ttl(keys[0]) <= 60


async def test_limiter_fails_open_when_redis_is_down(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(RateLimiter, "hit", AsyncMock(side_effect=RedisConnectionError("down")))
    resp = await client.post(LOGIN, data={"username": "a@example.com", "password": "whatever-123"})
    assert resp.status_code == 401  # reached the handler instead of erroring
    assert "X-RateLimit-Remaining" not in resp.headers


async def test_rate_limit_can_be_disabled(client: AsyncClient, app: FastAPI) -> None:
    app.state.settings.rate_limit_enabled = False
    for _ in range(7):
        resp = await client.post(
            LOGIN, data={"username": "a@example.com", "password": "whatever-123"}
        )
        assert resp.status_code == 401
