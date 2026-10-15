import uuid
from typing import Any

from fastapi import FastAPI
from httpx import AsyncClient

from tests.conftest import RegisterAndLogin

NOTES = "/api/v1/notes"


async def _create(client: AsyncClient, headers: dict[str, str], **fields: Any) -> dict[str, Any]:
    payload = {"title": "Untitled", **fields}
    resp = await client.post(NOTES, json=payload, headers=headers)
    assert resp.status_code == 201, resp.text
    body: dict[str, Any] = resp.json()
    return body


async def test_create_note_normalizes_tags(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    note = await _create(
        client,
        auth_headers,
        title="FastAPI tips",
        content="Use Depends.",
        tags=[" Python", "python", "API"],
    )
    assert note["title"] == "FastAPI tips"
    assert note["tags"] == ["api", "python"]  # deduped, lowercased, sorted by name
    assert note["word_count"] is None  # filled in later by the worker
    uuid.UUID(note["id"])


async def test_create_note_validation(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    for bad in (
        {"title": ""},
        {"title": "x" * 201},
        {"title": "ok", "tags": ["  "]},
        {"title": "ok", "tags": ["t"] * 21},
    ):
        resp = await client.post(NOTES, json=bad, headers=auth_headers)
        assert resp.status_code == 422, bad


async def test_create_note_enqueues_processing(
    client: AsyncClient, app: FastAPI, auth_headers: dict[str, str]
) -> None:
    note = await _create(client, auth_headers, title="Queued", content="hello")
    jobs = await app.state.redis.queued_jobs()
    assert [(j.function, j.args) for j in jobs] == [("process_note", (note["id"],))]


async def test_get_note_and_404s(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    note = await _create(client, auth_headers, title="Mine")
    resp = await client.get(f"{NOTES}/{note['id']}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["title"] == "Mine"

    missing = await client.get(f"{NOTES}/{uuid.uuid4()}", headers=auth_headers)
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"
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
    assert (await client.get(NOTES, headers=bob)).json()["total"] == 0

    # Tags are per user: Bob using the same tag name doesn't expose Alice's notes.
    await _create(client, bob, title="Bob's", tags=["private"])
    bob_private = (await client.get(NOTES, params={"tag": "private"}, headers=bob)).json()
    assert [n["title"] for n in bob_private["items"]] == ["Bob's"]
    assert (await client.get(url, headers=alice)).json()["title"] == "Alice's secret"


async def test_update_note_partial(
    client: AsyncClient, app: FastAPI, auth_headers: dict[str, str]
) -> None:
    note = await _create(client, auth_headers, title="Draft", content="v1", tags=["a"])
    await app.state.redis.flushdb()
    url = f"{NOTES}/{note['id']}"

    resp = await client.patch(url, json={"content": "v2"}, headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert (body["title"], body["content"], body["tags"]) == ("Draft", "v2", ["a"])
    assert body["updated_at"] >= note["updated_at"]
    assert len(await app.state.redis.queued_jobs()) == 1

    # Tag-only changes don't need reprocessing.
    await app.state.redis.flushdb()
    resp = await client.patch(url, json={"tags": ["b", "c"]}, headers=auth_headers)
    assert resp.json()["tags"] == ["b", "c"]
    assert await app.state.redis.queued_jobs() == []

    # Explicit null is rejected; omitting a field is how you leave it alone.
    assert (await client.patch(url, json={"title": None}, headers=auth_headers)).status_code == 422
    assert (await client.patch(url, json={"tags": None}, headers=auth_headers)).status_code == 422


async def test_delete_note(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    note = await _create(client, auth_headers)
    url = f"{NOTES}/{note['id']}"
    assert (await client.delete(url, headers=auth_headers)).status_code == 204
    assert (await client.get(url, headers=auth_headers)).status_code == 404
    assert (await client.delete(url, headers=auth_headers)).status_code == 404


async def test_list_pagination_newest_first(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    for i in range(5):
        await _create(client, auth_headers, title=f"note {i}")
    page1 = (await client.get(NOTES, params={"limit": 2}, headers=auth_headers)).json()
    page3 = (await client.get(NOTES, params={"limit": 2, "offset": 4}, headers=auth_headers)).json()
    assert page1["total"] == page3["total"] == 5
    assert [n["title"] for n in page1["items"]] == ["note 4", "note 3"]
    assert [n["title"] for n in page3["items"]] == ["note 0"]
    assert (await client.get(NOTES, params={"limit": 101}, headers=auth_headers)).status_code == 422


async def test_list_filter_by_tag(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    await _create(client, auth_headers, title="py", tags=["python"])
    await _create(client, auth_headers, title="both", tags=["python", "sql"])
    await _create(client, auth_headers, title="none")
    resp = (await client.get(NOTES, params={"tag": "Python"}, headers=auth_headers)).json()
    assert resp["total"] == 2
    assert {n["title"] for n in resp["items"]} == {"py", "both"}


async def test_full_text_search_ranks_title_matches_first(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    await _create(client, auth_headers, title="Groceries", content="milk, eggs")
    await _create(client, auth_headers, title="Weekend", content="read about postgres indexing")
    await _create(client, auth_headers, title="Postgres notes", content="indexes and vacuum")

    resp = (await client.get(NOTES, params={"q": "postgres"}, headers=auth_headers)).json()
    assert [n["title"] for n in resp["items"]] == ["Postgres notes", "Weekend"]

    # Stemming: "indexes" in the query matches "indexing" and "indexes".
    assert (await client.get(NOTES, params={"q": "indexes"}, headers=auth_headers)).json()[
        "total"
    ] == 2
    # websearch syntax: exclusion
    excl = (await client.get(NOTES, params={"q": "postgres -vacuum"}, headers=auth_headers)).json()
    assert [n["title"] for n in excl["items"]] == ["Weekend"]


async def test_notes_require_auth(client: AsyncClient) -> None:
    assert (await client.get(NOTES)).status_code == 401
    assert (await client.post(NOTES, json={"title": "x"})).status_code == 401
