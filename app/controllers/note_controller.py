import uuid

from fastapi import APIRouter, Depends, Query, status

from app.core.rate_limiting import rate_limit
from app.dependencies import get_current_user, get_note_service
from app.models.db.user import User
from app.models.note_model import (
    NoteCreateRequest,
    NoteListResponse,
    NoteResponse,
    NoteUpdateRequest,
)
from app.models.response_model import GlobalResponse, SuccessResponse
from app.services.note_service import NoteService

router = APIRouter(prefix="/notes", tags=["Notes"])

read_limit = [Depends(rate_limit("notes:read"))]
write_limit = [Depends(rate_limit("notes:write"))]


@router.post(
    "",
    response_model=GlobalResponse[NoteResponse],
    status_code=status.HTTP_201_CREATED,
    dependencies=write_limit,
)
async def create_note(
    body: NoteCreateRequest,
    user: User = Depends(get_current_user),
    service: NoteService = Depends(get_note_service),
) -> SuccessResponse[NoteResponse]:
    note = await service.create(user.id, body)
    return SuccessResponse(
        status=201, message="Note created", data=NoteResponse.model_validate(note)
    )


@router.get("", response_model=GlobalResponse[NoteListResponse], dependencies=read_limit)
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
) -> SuccessResponse[NoteListResponse]:
    items, total = await service.list_notes(user.id, limit=limit, offset=offset, tag=tag, query=q)
    page = NoteListResponse(
        items=[NoteResponse.model_validate(n) for n in items],
        total=total,
        limit=limit,
        offset=offset,
    )
    return SuccessResponse(data=page)


@router.get("/{note_id}", response_model=GlobalResponse[NoteResponse], dependencies=read_limit)
async def get_note(
    note_id: uuid.UUID,
    user: User = Depends(get_current_user),
    service: NoteService = Depends(get_note_service),
) -> SuccessResponse[NoteResponse]:
    note = await service.get(user.id, note_id)
    return SuccessResponse(data=NoteResponse.model_validate(note))


@router.patch("/{note_id}", response_model=GlobalResponse[NoteResponse], dependencies=write_limit)
async def update_note(
    note_id: uuid.UUID,
    body: NoteUpdateRequest,
    user: User = Depends(get_current_user),
    service: NoteService = Depends(get_note_service),
) -> SuccessResponse[NoteResponse]:
    note = await service.update(user.id, note_id, body)
    return SuccessResponse(message="Note updated", data=NoteResponse.model_validate(note))


@router.delete("/{note_id}", response_model=GlobalResponse[None], dependencies=write_limit)
async def delete_note(
    note_id: uuid.UUID,
    user: User = Depends(get_current_user),
    service: NoteService = Depends(get_note_service),
) -> SuccessResponse[None]:
    await service.delete(user.id, note_id)
    return SuccessResponse(message="Note deleted")
