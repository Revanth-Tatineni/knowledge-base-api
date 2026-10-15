import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from app.models.note import Note
from app.repositories.token_repo import RefreshTokenRepository
from app.services.text_analysis import analyze

logger = logging.getLogger(__name__)


async def process_note(ctx: dict[str, Any], note_id: str) -> dict[str, Any] | None:
    """Compute word count, reading time and keywords for a note.

    Idempotent: it always reads the note's current text, so duplicate or out-of-order jobs
    for the same note converge on the right result.
    """
    async with ctx["session_factory"]() as session:
        note = await session.get(Note, uuid.UUID(note_id))
        if note is None:
            logger.info("Note gone before processing", extra={"fields": {"note_id": note_id}})
            return None
        stats = analyze(note.title, note.content)
        note.word_count = stats.word_count
        note.reading_time_minutes = stats.reading_time_minutes
        note.keywords = stats.keywords
        note.processed_at = datetime.now(UTC)
        await session.commit()
        return {"note_id": note_id, "word_count": stats.word_count, "keywords": stats.keywords}


async def purge_expired_refresh_tokens(ctx: dict[str, Any]) -> int:
    async with ctx["session_factory"]() as session:
        deleted = await RefreshTokenRepository(session).delete_expired(datetime.now(UTC))
        await session.commit()
    logger.info("Purged expired refresh tokens", extra={"fields": {"deleted": deleted}})
    return deleted
