"""ARQ worker entrypoint: `arq app.worker.settings.WorkerSettings`."""

import logging
from typing import Any, ClassVar

from arq import cron
from arq.connections import RedisSettings

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import create_engine, create_session_factory
from app.worker.tasks import process_note, purge_expired_refresh_tokens

settings = get_settings()


async def startup(ctx: dict[str, Any]) -> None:
    configure_logging(settings.log_level)
    # arq installs its own plain-text handler; drop it so each line is logged once, as JSON.
    logging.getLogger("arq").handlers.clear()
    ctx["engine"] = create_engine(settings.database_url)
    ctx["session_factory"] = create_session_factory(ctx["engine"])


async def shutdown(ctx: dict[str, Any]) -> None:
    await ctx["engine"].dispose()


class WorkerSettings:
    functions: ClassVar = [process_note]
    cron_jobs: ClassVar = [cron(purge_expired_refresh_tokens, hour={3}, minute={0})]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    max_tries = 3
    job_timeout = 30
