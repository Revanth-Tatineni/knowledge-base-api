import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import func, select

from app.models.db.refresh_token import RefreshToken
from app.services.text_analysis import analyze
from app.workers.tasks import process_note, purge_expired_refresh_tokens
from tests.conftest import RegisterAndLogin, data


def test_analyze_counts_words_and_reading_time() -> None:
    stats = analyze("t", "word " * 401)
    assert stats.word_count == 401
    assert stats.reading_time_minutes == 3  # ceil(401 / 200)
    assert analyze("t", "").reading_time_minutes == 0
    assert analyze("t", "one").reading_time_minutes == 1


def test_analyze_keywords_skip_stopwords_short_words_and_numbers() -> None:
    stats = analyze(
        "Postgres indexing",
        "The postgres planner uses an index. Indexing in postgres is fast; "
        "2024 2024 2024 is a year.",
    )
    assert stats.keywords[0] == "postgres"
    assert "indexing" in stats.keywords
    assert not {"the", "is", "an", "in", "2024", "a"} & set(stats.keywords)
    assert len(stats.keywords) <= 5


def test_analyze_keyword_ties_are_deterministic() -> None:
    assert analyze("", "zebra apple mango").keywords == ["apple", "mango", "zebra"]


async def test_process_note_fills_stats(
    client: AsyncClient, app: FastAPI, auth_headers: dict[str, str]
) -> None:
    created = data(
        await client.post(
            "/api/v1/notes",
            json={"title": "Redis", "content": "Redis streams and redis pubsub"},
            headers=auth_headers,
        )
    )
    ctx: dict[str, Any] = {"db": app.state.db}
    result = await process_note(ctx, created["id"])
    assert result is not None and result["word_count"] == 5

    note = data(await client.get(f"/api/v1/notes/{created['id']}", headers=auth_headers))
    assert note["word_count"] == 5
    assert note["reading_time_minutes"] == 1
    assert note["keywords"][0] == "redis"
    assert note["processed_at"] is not None


async def test_process_note_for_deleted_note_is_a_noop(app: FastAPI) -> None:
    ctx: dict[str, Any] = {"db": app.state.db}
    assert await process_note(ctx, str(uuid.uuid4())) is None


async def test_purge_expired_refresh_tokens(
    app: FastAPI, register_and_login: RegisterAndLogin
) -> None:
    await register_and_login("a@example.com")
    await register_and_login("b@example.com")
    async with app.state.db.session_factory() as session:
        token = (await session.execute(select(RefreshToken).limit(1))).scalar_one()
        token.expires_at = datetime.now(UTC) - timedelta(days=1)
        await session.commit()

    ctx: dict[str, Any] = {"db": app.state.db}
    assert await purge_expired_refresh_tokens(ctx) == 1
    async with app.state.db.session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(RefreshToken)) == 1


async def test_note_still_saved_when_queue_is_down(
    client: AsyncClient, app: FastAPI, auth_headers: dict[str, str], monkeypatch: Any
) -> None:
    from redis.exceptions import ConnectionError as RedisConnectionError

    async def down(*args: Any, **kwargs: Any) -> None:
        raise RedisConnectionError("queue down")

    monkeypatch.setattr(app.state.redis.pool, "enqueue_job", down)
    resp = await client.post("/api/v1/notes", json={"title": "Still saved"}, headers=auth_headers)
    assert resp.status_code == 201
