import uuid
from typing import Any

from fastapi import FastAPI
from httpx import AsyncClient

from tests.conftest import RegisterAndLogin, data, error_code

NOTES = "/api/v1/notes"


async def _create(client: AsyncClient, headers: dict[str, str], **fields: Any) -> dict[str, Any]:
    payload = {"title": "Untitled", **fields}
    resp = await client.post(NOTES, json=payload, headers=headers)
    assert resp.status_code == 201, resp.text
    note: dict[str, Any] = data(resp)
    return note


async def _list(client: AsyncClient, headers: dict[str, str], **params: Any) -> dict[str, Any]:
    resp = await client.get(NOTES, params=params, headers=headers)
    assert resp.status_code == 200, resp.text
    page: dict[str, Any] = data(resp)
    return page


async def test_create_note_returns_envelope_and_normalizes_tags(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    resp = await client.post(
        NOTES,
        json={
            "title": "FastAPI tips",
            "content": "Use Depends.",
            "tags": [" Python", "python", "API"],
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert (body["status"], body["message"], body["errors"]) == (201, "Note created", [])
    note = body["data"]
    assert note["title"] == "FastAPI tips"
    assert note["tags"] == ["api", "python"]  # deduped, lowercased, sorted by name
    assert note["word_count"] is None  # filled in later by the worker
    uuid.UUID(note["id"])


async def test_create_note_validation(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    bad_payloads = [
        {"title": ""},
        {"title": "x" * 201},
        {"title": "ok", "tags": ["  "]},
        {"title": "ok", "tags": ["t"] * 21},
    ]
    for bad in bad_payloads:
        resp = await client.post(NOTES, json=bad, headers=auth_headers)
        assert resp.status_code == 422, bad
        assert error_code(resp) == "VALIDATION_ERROR"


async def test_create_note_enqueues_processing(
    client: AsyncClient, app: FastAPI, auth_headers: dict[str, str]
) -> None:
    note = await _create(client, auth_headers, title="Queued", content="hello")
    jobs = await app.state.redis.pool.queued_jobs()
    assert [(j.function, j.args) for j in jobs] == [("process_note", (note["id"],))]


async def test_get_note_and_404s(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    note = await _create(client, auth_headers, title="Mine")
    resp = await client.get(f"{NOTES}/{note['id']}", headers=auth_headers)
    assert resp.status_code == 200
    assert data(resp)["title"] == "Mine"

    missing = await client.get(f"{NOTES}/{uuid.uuid4()}", headers=auth_headers)
    assert missing.status_code == 404
    assert error_code(missing) == "NOT_FOUND"
    assert (await client.get(f"{NOTES}/not-a-uuid", headers=auth_headers)).status_code == 422


async def test_users_cannot_see_or_touch_each_others_notes(
    client: AsyncClient, register_and_login: RegisterAndLogin
) -> None:
    alice = (await register_and_login("alice@example.com"))["headers"]
    bob = (await register_and_login("bob@example.com"))["headers"]
    note = await _create(client, alice, title="Alice's secret", tags=["private"])
    url = f"{NOTES}/{note['id']}"

    assert (await client.get(url, headers=bob)).status_code == 404
    assert (await client.patch(url, json={"title": "pwned"}, headers=bob)).status_code == 404
    assert (await client.delete(url, headers=bob)).status_code == 404
    assert (await _list(client, bob))["total"] == 0

    # Tags are per user: Bob using the same tag name doesn't expose Alice's notes.
    await _create(client, bob, title="Bob's", tags=["private"])
    bob_private = await _list(client, bob, tag="private")
    assert [n["title"] for n in bob_private["items"]] == ["Bob's"]
    assert data(await client.get(url, headers=alice))["title"] == "Alice's secret"


async def test_update_note_partial(
    client: AsyncClient, app: FastAPI, auth_headers: dict[str, str]
) -> None:
    note = await _create(client, auth_headers, title="Draft", content="v1", tags=["a"])
    await app.state.redis.pool.flushdb()
    url = f"{NOTES}/{note['id']}"

    resp = await client.patch(url, json={"content": "v2"}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["message"] == "Note updated"
    body = data(resp)
    assert (body["title"], body["content"], body["tags"]) == ("Draft", "v2", ["a"])
    assert body["updated_at"] >= note["updated_at"]
    assert len(await app.state.redis.pool.queued_jobs()) == 1

    # Tag-only changes don't need reprocessing.
    await app.state.redis.pool.flushdb()
    resp = await client.patch(url, json={"tags": ["b", "c"]}, headers=auth_headers)
    assert data(resp)["tags"] == ["b", "c"]
    assert await app.state.redis.pool.queued_jobs() == []

    # Explicit null is rejected; omitting a field is how you leave it alone.
    assert (await client.patch(url, json={"title": None}, headers=auth_headers)).status_code == 422
    assert (await client.patch(url, json={"tags": None}, headers=auth_headers)).status_code == 422


async def test_delete_note(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    note = await _create(client, auth_headers)
    url = f"{NOTES}/{note['id']}"
    resp = await client.delete(url, headers=auth_headers)
    assert resp.status_code == 200
    assert (resp.json()["message"], resp.json()["data"]) == ("Note deleted", None)
    assert (await client.get(url, headers=auth_headers)).status_code == 404
    assert (await client.delete(url, headers=auth_headers)).status_code == 404


async def test_list_pagination_newest_first(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    for i in range(5):
        await _create(client, auth_headers, title=f"note {i}")
    page1 = await _list(client, auth_headers, limit=2)
    page3 = await _list(client, auth_headers, limit=2, offset=4)
    assert page1["total"] == page3["total"] == 5
    assert [n["title"] for n in page1["items"]] == ["note 4", "note 3"]
    assert [n["title"] for n in page3["items"]] == ["note 0"]
    too_big = await client.get(NOTES, params={"limit": 101}, headers=auth_headers)
    assert too_big.status_code == 422


async def test_list_filter_by_tag(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    await _create(client, auth_headers, title="py", tags=["python"])
    await _create(client, auth_headers, title="both", tags=["python", "sql"])
    await _create(client, auth_headers, title="none")
    page = await _list(client, auth_headers, tag="Python")
    assert page["total"] == 2
    assert {n["title"] for n in page["items"]} == {"py", "both"}


async def test_full_text_search_ranks_title_matches_first(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    await _create(client, auth_headers, title="Groceries", content="milk, eggs")
    await _create(client, auth_headers, title="Weekend", content="read about postgres indexing")
    await _create(client, auth_headers, title="Postgres notes", content="indexes and vacuum")

    found = await _list(client, auth_headers, q="postgres")
    assert [n["title"] for n in found["items"]] == ["Postgres notes", "Weekend"]

    # Stemming: "indexes" in the query matches "indexing" and "indexes".
    assert (await _list(client, auth_headers, q="indexes"))["total"] == 2
    # websearch syntax: exclusion
    excluded = await _list(client, auth_headers, q="postgres -vacuum")
    assert [n["title"] for n in excluded["items"]] == ["Weekend"]


async def test_notes_require_auth(client: AsyncClient) -> None:
    assert (await client.get(NOTES)).status_code == 401
    assert (await client.post(NOTES, json={"title": "x"})).status_code == 401
