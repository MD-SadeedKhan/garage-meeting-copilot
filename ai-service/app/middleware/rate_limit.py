"""
Garage Meeting Copilot — Rate Limiting Middleware
Per-user, per-IP rate limiting using Redis sliding window.
"""
from __future__ import annotations

import time
from typing import Callable

from fastapi import HTTPException, Request, Response, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.redis import get_redis

logger = get_logger(__name__)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Sliding window rate limiter using Redis.
    Limits by authenticated user_id when available, else by IP.
    """

    # Endpoints exempt from rate limiting
    EXEMPT_PATHS = {"/health", "/nginx-health", "/favicon.ico"}

    def __init__(self, app: ASGIApp, requests_per_minute: int = 120) -> None:
        super().__init__(app)
        self._limit = requests_per_minute
        self._window = 60  # seconds

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.url.path in self.EXEMPT_PATHS:
            return await call_next(request)

        # Determine rate limit key: user ID > forwarded IP > direct IP
        identifier = self._get_identifier(request)

        redis = get_redis()
        key = f"copilot:rl:{identifier}"
        now = time.time()
        window_start = now - self._window

        async with redis.pipeline(transaction=True) as pipe:
            # Remove timestamps outside the window
            pipe.zremrangebyscore(key, 0, window_start)
            # Count requests in window
            pipe.zcard(key)
            # Add current request timestamp
            pipe.zadd(key, {str(now): now})
            # Set expiry
            pipe.expire(key, self._window + 5)
            results = await pipe.execute()

        current_count = results[1]

        if current_count >= self._limit:
            logger.warning(
                "rate_limit_exceeded",
                identifier=identifier,
                count=current_count,
                limit=self._limit,
            )
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded. Please slow down.",
                headers={
                    "Retry-After": str(self._window),
                    "X-RateLimit-Limit": str(self._limit),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(int(now + self._window)),
                },
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(self._limit)
        response.headers["X-RateLimit-Remaining"] = str(
            max(0, self._limit - current_count - 1)
        )
        return response

    def _get_identifier(self, request: Request) -> str:
        # Use auth context if available (set by JWT middleware)
        auth = getattr(request.state, "auth", None)
        if auth and hasattr(auth, "user_id"):
            return f"user:{auth.user_id}"

        # Fall back to IP
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            ip = forwarded_for.split(",")[0].strip()
        else:
            ip = request.client.host if request.client else "unknown"
        return f"ip:{ip}"
