import logging
from collections.abc import AsyncIterator, Awaitable, Callable

from arq.connections import ArqRedis
from fastapi import Depends, Request
from fastapi.security import OAuth2PasswordBearer
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import RateLimitedError, UnauthorizedError
from app.core.rate_limit import RateLimiter
from app.core.security import InvalidTokenError, decode_access_token
from app.models.user import User
from app.repositories.user_repo import UserRepository
from app.services.auth_service import AuthService
from app.services.note_service import NoteService

logger = logging.getLogger(__name__)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


def get_settings_dep(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_queue(request: Request) -> ArqRedis:
    queue: ArqRedis = request.app.state.redis
    return queue


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.session_factory() as session:
        yield session


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings_dep),
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
    settings: Settings = Depends(get_settings_dep),
) -> AuthService:
    return AuthService(session, settings)


def get_note_service(
    session: AsyncSession = Depends(get_session), queue: ArqRedis = Depends(get_queue)
) -> NoteService:
    return NoteService(session, queue)


async def _enforce_rate_limit(request: Request, scope: str, identity: str, limit: int) -> None:
    settings: Settings = request.app.state.settings
    if not settings.rate_limit_enabled:
        return
    limiter = RateLimiter(request.app.state.redis)
    try:
        result = await limiter.hit(scope, identity, limit, settings.rate_limit_window_seconds)
    except (RedisError, OSError):
        # Fail open: a Redis outage shouldn't take the whole API down with it.
        logger.warning("Rate limiter unavailable; allowing request", exc_info=True)
        return
    headers = {
        "X-RateLimit-Limit": str(result.limit),
        "X-RateLimit-Remaining": str(result.remaining),
        "X-RateLimit-Reset": str(result.reset_in),
    }
    if not result.allowed:
        raise RateLimitedError(headers={**headers, "Retry-After": str(result.reset_in)})
    # Attached by the request middleware, so they're present even if the endpoint later
    # fails (e.g. a 401 on login), which is exactly when a client needs to see them.
    request.state.rate_limit_headers = headers


def limit_by_ip(scope: str) -> Callable[[Request], Awaitable[None]]:
    """Strict per-IP limit for unauthenticated endpoints (login, register)."""

    async def dependency(request: Request) -> None:
        ip = request.client.host if request.client else "unknown"
        limit = request.app.state.settings.rate_limit_auth
        await _enforce_rate_limit(request, scope, ip, limit)

    return dependency


async def limit_by_user(request: Request, user: User = Depends(get_current_user)) -> None:
    """General per-user limit for authenticated endpoints."""
    limit = request.app.state.settings.rate_limit_default
    await _enforce_rate_limit(request, "user", str(user.id), limit)
