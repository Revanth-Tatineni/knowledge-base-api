import time
from dataclasses import dataclass

from redis.asyncio import Redis


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    limit: int
    remaining: int
    reset_in: int  # seconds until the current window ends


class RateLimiter:
    """Fixed-window counter in Redis: one key per (scope, identity, window)."""

    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    async def hit(self, scope: str, identity: str, limit: int, window: int) -> RateLimitResult:
        now = int(time.time())
        window_start = now - now % window
        key = f"rl:{scope}:{identity}:{window_start}"
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.incr(key)
            pipe.expire(key, window, nx=True)
            count, _ = await pipe.execute()
        return RateLimitResult(
            allowed=count <= limit,
            limit=limit,
            remaining=max(limit - count, 0),
            reset_in=window_start + window - now,
        )
