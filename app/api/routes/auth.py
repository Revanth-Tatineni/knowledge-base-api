from fastapi import APIRouter, Depends, status
from fastapi.security import OAuth2PasswordRequestForm

from app.api.deps import get_auth_service, limit_by_ip
from app.schemas.auth import RefreshRequest, RegisterRequest, TokenPair
from app.schemas.user import UserRead
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(limit_by_ip("register"))],
)
async def register(
    body: RegisterRequest, service: AuthService = Depends(get_auth_service)
) -> UserRead:
    user = await service.register(body)
    return UserRead.model_validate(user)


@router.post("/login", response_model=TokenPair, dependencies=[Depends(limit_by_ip("login"))])
async def login(
    form: OAuth2PasswordRequestForm = Depends(), service: AuthService = Depends(get_auth_service)
) -> TokenPair:
    # OAuth2 password form (username field carries the email) so Swagger's Authorize works.
    return await service.login(form.username, form.password)


@router.post("/refresh", response_model=TokenPair, dependencies=[Depends(limit_by_ip("refresh"))])
async def refresh(
    body: RefreshRequest, service: AuthService = Depends(get_auth_service)
) -> TokenPair:
    return await service.refresh(body.refresh_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(body: RefreshRequest, service: AuthService = Depends(get_auth_service)) -> None:
    await service.logout(body.refresh_token)
