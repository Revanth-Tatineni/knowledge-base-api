"""FastAPI dependency wiring: settings, current user, and service instances for controllers."""

from fastapi import Depends, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.env import Settings
from app.core.exception import UnauthorizedError
from app.core.redis import RedisClient, get_redis
from app.core.security import InvalidTokenError, decode_access_token
from app.models.db.user import User
from app.repositories.user_repo import UserRepository
from app.services.auth_service import AuthService
from app.services.note_service import NoteService

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


def get_app_settings(request: Request) -> Settings:
    # Read from the app rather than the module-level `settings`, so tests can run an app
    # with their own Settings.
    settings: Settings = request.app.state.settings
    return settings


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
) -> User:
    try:
        user_id = decode_access_token(token, settings)
    except InvalidTokenError as exc:
        raise UnauthorizedError() from exc
    user = await UserRepository(session).get_by_id(user_id)
    if user is None or not user.is_active:
        raise UnauthorizedError()
    return user


def get_auth_service(
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
) -> AuthService:
    return AuthService(session, settings)


def get_note_service(
    session: AsyncSession = Depends(get_session), redis: RedisClient = Depends(get_redis)
) -> NoteService:
    return NoteService(session, redis)
