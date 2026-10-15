import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_TAGS = 20


def _normalize_tags(tags: list[str]) -> list[str]:
    cleaned: list[str] = []
    for raw in tags:
        tag = raw.strip().lower()
        if not tag:
            raise ValueError("tags must not be blank")
        if len(tag) > 50:
            raise ValueError("tags must be at most 50 characters")
        if tag not in cleaned:
            cleaned.append(tag)
    return cleaned


class NoteCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(default="", max_length=100_000)
    tags: list[str] = Field(default_factory=list, max_length=MAX_TAGS)

    @field_validator("tags")
    @classmethod
    def _tags(cls, value: list[str]) -> list[str]:
        return _normalize_tags(value)


class NoteUpdate(BaseModel):
    """PATCH body: only fields that are sent get changed. `tags` replaces the full set."""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    content: str | None = Field(default=None, max_length=100_000)
    tags: list[str] | None = Field(default=None, max_length=MAX_TAGS)

    @field_validator("title", "content")
    @classmethod
    def _not_null(cls, value: str | None) -> str:
        if value is None:
            raise ValueError("may be omitted but not null")
        return value

    @field_validator("tags")
    @classmethod
    def _tags(cls, value: list[str] | None) -> list[str]:
        if value is None:
            raise ValueError("may be omitted but not null")
        return _normalize_tags(value)


class NoteRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    content: str
    tags: list[str]
    word_count: int | None
    reading_time_minutes: int | None
    keywords: list[str] | None
    processed_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @field_validator("tags", mode="before")
    @classmethod
    def _tag_names(cls, value: list[Any]) -> list[str]:
        return [tag if isinstance(tag, str) else tag.name for tag in value]


class NotePage(BaseModel):
    items: list[NoteRead]
    total: int
    limit: int
    offset: int
