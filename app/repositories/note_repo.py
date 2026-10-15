import uuid

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.note import Note, Tag


class NoteRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, note: Note) -> Note:
        self.session.add(note)
        await self.session.flush()
        return note

    async def get_for_owner(self, note_id: uuid.UUID, owner_id: uuid.UUID) -> Note | None:
        result = await self.session.execute(
            select(Note).where(Note.id == note_id, Note.owner_id == owner_id)
        )
        return result.scalar_one_or_none()

    async def list_for_owner(
        self,
        owner_id: uuid.UUID,
        *,
        limit: int,
        offset: int,
        tag: str | None = None,
        query: str | None = None,
    ) -> tuple[list[Note], int]:
        stmt = select(Note).where(Note.owner_id == owner_id)
        if tag:
            stmt = stmt.where(Note.tags.any(Tag.name == tag.lower()))
        if query:
            ts_query = func.websearch_to_tsquery("english", query)
            stmt = stmt.where(Note.search_vector.op("@@")(ts_query)).order_by(
                func.ts_rank(Note.search_vector, ts_query).desc(), Note.created_at.desc()
            )
        else:
            stmt = stmt.order_by(Note.created_at.desc(), Note.id.desc())

        total = await self.session.scalar(
            select(func.count()).select_from(stmt.order_by(None).subquery())
        )
        result = await self.session.execute(stmt.limit(limit).offset(offset))
        return list(result.scalars().all()), int(total or 0)

    async def delete(self, note: Note) -> None:
        await self.session.delete(note)
        await self.session.flush()

    async def get_or_create_tags(self, owner_id: uuid.UUID, names: list[str]) -> list[Tag]:
        if not names:
            return []
        # Upsert-then-select is race-safe: two requests creating the same new tag at once
        # won't trip the (owner_id, name) unique constraint.
        await self.session.execute(
            insert(Tag)
            .values([{"id": uuid.uuid4(), "owner_id": owner_id, "name": n} for n in names])
            .on_conflict_do_nothing(index_elements=["owner_id", "name"])
        )
        result = await self.session.execute(
            select(Tag).where(Tag.owner_id == owner_id, Tag.name.in_(names))
        )
        by_name = {tag.name: tag for tag in result.scalars()}
        # Sorted to match the relationship's order_by, so a fresh write and a later read agree.
        return [by_name[n] for n in sorted(names)]
