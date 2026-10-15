import uuid
from datetime import datetime

from sqlalchemy import (
    Column,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

note_tags = Table(
    "note_tags",
    Base.metadata,
    Column("note_id", ForeignKey("notes.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
    # The PK covers lookups by note_id; this covers "which notes have tag X".
    Index("ix_note_tags_tag_id", "tag_id"),
)

# Title matches weigh more than body matches when ranking search results.
SEARCH_VECTOR_SQL = (
    "setweight(to_tsvector('english', coalesce(title, '')), 'A') || "
    "setweight(to_tsvector('english', coalesce(content, '')), 'B')"
)


class Tag(Base):
    __tablename__ = "tags"
    __table_args__ = (UniqueConstraint("owner_id", "name"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(50))


class Note(TimestampMixin, Base):
    __tablename__ = "notes"
    __table_args__ = (
        Index("ix_notes_owner_id_created_at", "owner_id", "created_at"),
        Index("ix_notes_search_vector", "search_vector", postgresql_using="gin"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text, default="", server_default="")

    # Filled in by the background worker after each create/update.
    word_count: Mapped[int | None] = mapped_column(Integer)
    reading_time_minutes: Mapped[int | None] = mapped_column(Integer)
    keywords: Mapped[list[str] | None] = mapped_column(ARRAY(String(50)))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    search_vector: Mapped[str] = mapped_column(
        TSVECTOR, Computed(SEARCH_VECTOR_SQL, persisted=True), deferred=True
    )

    tags: Mapped[list[Tag]] = relationship(secondary=note_tags, lazy="selectin", order_by=Tag.name)
