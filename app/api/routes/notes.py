import uuid

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import get_current_user, get_note_service, limit_by_user
from app.models.user import User
from app.schemas.note import NoteCreate, NotePage, NoteRead, NoteUpdate
from app.services.note_service import NoteService

router = APIRouter(prefix="/notes", tags=["notes"], dependencies=[Depends(limit_by_user)])


@router.post("", response_model=NoteRead, status_code=status.HTTP_201_CREATED)
async def create_note(
    body: NoteCreate,
    user: User = Depends(get_current_user),
    service: NoteService = Depends(get_note_service),
) -> NoteRead:
    return NoteRead.model_validate(await service.create(user.id, body))


@router.get("", response_model=NotePage)
async def list_notes(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    tag: str | None = Query(None, max_length=50, description="Only notes with this tag"),
    q: str | None = Query(
        None,
        min_length=1,
        max_length=200,
        description='Full-text search; supports "quoted phrases", OR, and -exclusions',
    ),
    user: User = Depends(get_current_user),
    service: NoteService = Depends(get_note_service),
) -> NotePage:
    items, total = await service.list_notes(user.id, limit=limit, offset=offset, tag=tag, query=q)
    return NotePage(
        items=[NoteRead.model_validate(n) for n in items], total=total, limit=limit, offset=offset
    )


@router.get("/{note_id}", response_model=NoteRead)
async def get_note(
    note_id: uuid.UUID,
    user: User = Depends(get_current_user),
    service: NoteService = Depends(get_note_service),
) -> NoteRead:
    return NoteRead.model_validate(await service.get(user.id, note_id))


@router.patch("/{note_id}", response_model=NoteRead)
async def update_note(
    note_id: uuid.UUID,
    body: NoteUpdate,
    user: User = Depends(get_current_user),
    service: NoteService = Depends(get_note_service),
) -> NoteRead:
    return NoteRead.model_validate(await service.update(user.id, note_id, body))


@router.delete("/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_note(
    note_id: uuid.UUID,
    user: User = Depends(get_current_user),
    service: NoteService = Depends(get_note_service),
) -> None:
    await service.delete(user.id, note_id)
