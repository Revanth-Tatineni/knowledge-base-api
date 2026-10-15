import uuid
from datetime import UTC, datetime

from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exception import NotFoundError
from app.core.logger import get_logger
from app.core.redis import RedisClient
from app.models.db.note import Note
from app.models.note_model import NoteCreateRequest, NoteUpdateRequest
from app.repositories.note_repo import NoteRepository

logger = get_logger(__name__)

PROCESS_NOTE_TASK = "process_note"


class NoteService:
    def __init__(self, session: AsyncSession, redis: RedisClient) -> None:
        self.session = session
        self.redis = redis
        self.notes = NoteRepository(session)

    async def create(self, owner_id: uuid.UUID, data: NoteCreateRequest) -> Note:
        note = Note(owner_id=owner_id, title=data.title, content=data.content)
        note.tags = await self.notes.get_or_create_tags(owner_id, data.tags)
        await self.notes.add(note)
        await self.session.commit()
        await self._enqueue_processing(note.id)
        return note

    async def get(self, owner_id: uuid.UUID, note_id: uuid.UUID) -> Note:
        note = await self.notes.get_for_owner(note_id, owner_id)
        if note is None:
            # Same 404 whether the note doesn't exist or belongs to someone else, so IDs
            # can't be probed.
            raise NotFoundError("Note not found")
        return note

    async def list_notes(
        self,
        owner_id: uuid.UUID,
        *,
        limit: int,
        offset: int,
        tag: str | None,
        query: str | None,
    ) -> tuple[list[Note], int]:
        return await self.notes.list_for_owner(
            owner_id, limit=limit, offset=offset, tag=tag, query=query
        )

    async def update(
        self, owner_id: uuid.UUID, note_id: uuid.UUID, data: NoteUpdateRequest
    ) -> Note:
        note = await self.get(owner_id, note_id)
        changes = data.model_dump(exclude_unset=True)
        text_changed = False
        if "title" in changes and changes["title"] != note.title:
            note.title = changes["title"]
            text_changed = True
        if "content" in changes and changes["content"] != note.content:
            note.content = changes["content"]
            text_changed = True
        if "tags" in changes:
            note.tags = await self.notes.get_or_create_tags(owner_id, changes["tags"])
        if changes:
            # Set explicitly so a tags-only change (no UPDATE on the notes row) still bumps it.
            note.updated_at = datetime.now(UTC)
        await self.session.commit()
        if text_changed:
            await self._enqueue_processing(note.id)
        return note

    async def delete(self, owner_id: uuid.UUID, note_id: uuid.UUID) -> None:
        note = await self.get(owner_id, note_id)
        await self.notes.delete(note)
        await self.session.commit()

    async def _enqueue_processing(self, note_id: uuid.UUID) -> None:
        # The note is already committed; if the queue is down we log and move on rather than
        # failing a write the user already made. The stats just stay empty until the next edit.
        try:
            await self.redis.enqueue(PROCESS_NOTE_TASK, str(note_id))
        except (RedisError, OSError):
            logger.warning(
                "Could not enqueue note processing",
                extra={"fields": {"note_id": str(note_id)}},
                exc_info=True,
            )
