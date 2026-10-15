"""App factory. Also the command entrypoint: `python -m app.main <command>` (see app/cli.py)."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.controllers import auth_controller, health_controller, note_controller, user_controller
from app.core.cors import setup_cors
from app.core.db import init_db
from app.core.env import Settings, get_settings
from app.core.exception import register_exception_handlers
from app.core.logger import get_logger, setup_logging
from app.core.redis import RedisClient
from app.middleware.request_context import register_request_context
from app.models.response_model import GlobalResponse, SuccessResponse

logger = get_logger(__name__)

API_PREFIX = "/api/v1"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    setup_logging(settings.LOG_LEVEL, json_logs=settings.ENVIRONMENT != "local")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Created once per process and shared by every request; closed on shutdown.
        app.state.db = init_db(settings)
        app.state.redis = await RedisClient.connect(settings.REDIS_URL)
        logger.info("[startup] Database pool and Redis ready")
        try:
            yield
        finally:
            await app.state.redis.close()
            await app.state.db.close()
            logger.info("[shutdown] Connections closed")

    app = FastAPI(
        title=settings.PROJECT_NAME,
        version="0.1.0",
        description="Personal knowledge base: notes, tags, full-text search.",
        lifespan=lifespan,
    )
    app.state.settings = settings

    setup_cors(app, settings)
    register_request_context(app)
    register_exception_handlers(app)

    app.include_router(health_controller.router)
    for controller in (auth_controller, user_controller, note_controller):
        app.include_router(controller.router, prefix=API_PREFIX)

    @app.get("/", tags=["Health"], response_model=GlobalResponse[dict[str, str]])
    async def root() -> SuccessResponse[dict[str, str]]:
        return SuccessResponse(
            message=f"Welcome to {settings.PROJECT_NAME}", data={"docs": "/docs"}
        )

    return app


app = create_app()


if __name__ == "__main__":
    from app.cli import main

    main()
