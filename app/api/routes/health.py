import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

router = APIRouter(prefix="/health", tags=["health"])
logger = logging.getLogger(__name__)


@router.get("/live")
async def live() -> dict[str, str]:
    """Process is up. Used by the orchestrator to decide whether to restart the container."""
    return {"status": "ok"}


@router.get("/ready")
async def ready(request: Request) -> JSONResponse:
    """Dependencies reachable. Used to decide whether to send this instance traffic."""
    checks: dict[str, str] = {}
    try:
        async with request.app.state.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:
        logger.warning("Readiness: database check failed", exc_info=True)
        checks["database"] = "unavailable"
    try:
        await request.app.state.redis.ping()
        checks["redis"] = "ok"
    except Exception:
        logger.warning("Readiness: redis check failed", exc_info=True)
        checks["redis"] = "unavailable"

    healthy = all(v == "ok" for v in checks.values())
    return JSONResponse(
        {"status": "ok" if healthy else "degraded", "checks": checks},
        status_code=200 if healthy else 503,
    )
