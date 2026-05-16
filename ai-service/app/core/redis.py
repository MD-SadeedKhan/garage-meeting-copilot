"""
Garage Meeting Copilot — Redis Layer
Async Redis client, pub/sub manager, and stream state.
"""
from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import redis.asyncio as aioredis
from redis.asyncio import Redis
from redis.asyncio.client import PubSub

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_redis_pool: aioredis.ConnectionPool | None = None
_redis_client: Redis | None = None


def _build_pool() -> aioredis.ConnectionPool:
    settings = get_settings()
    return aioredis.ConnectionPool.from_url(
        settings.redis_url,
        max_connections=settings.redis_max_connections,
        decode_responses=True,
        health_check_interval=30,
    )


def get_redis() -> Redis:
    global _redis_pool, _redis_client
    if _redis_client is None:
        _redis_pool = _build_pool()
        _redis_client = Redis(connection_pool=_redis_pool)
    return _redis_client


async def check_redis_connection() -> bool:
    try:
        r = get_redis()
        await r.ping()
        return True
    except Exception as e:
        logger.error("redis_health_check_failed", error=str(e))
        return False


async def close_redis() -> None:
    global _redis_client, _redis_pool
    if _redis_client:
        await _redis_client.aclose()
        _redis_client = None
    if _redis_pool:
        await _redis_pool.aclose()
        _redis_pool = None


class RedisStreamState:
    """
    Manages realtime state for active meeting sessions.
    Provides transcript buffering, session metadata, and pub/sub.
    """

    PREFIX = "copilot"
    TRANSCRIPT_TTL = 86400  # 24 hours
    SESSION_TTL = 14400     # 4 hours

    def __init__(self, redis: Redis) -> None:
        self._r = redis

    # ── Key builders ─────────────────────────

    def _session_key(self, session_id: str) -> str:
        return f"{self.PREFIX}:session:{session_id}"

    def _transcript_key(self, session_id: str) -> str:
        return f"{self.PREFIX}:transcript:{session_id}"

    def _suggestions_key(self, session_id: str) -> str:
        return f"{self.PREFIX}:suggestions:{session_id}"

    def _channel_key(self, session_id: str, channel: str) -> str:
        return f"{self.PREFIX}:{channel}:{session_id}"

    # ── Session state ─────────────────────────

    async def create_session(
        self,
        session_id: str,
        meeting_id: str,
        user_id: str,
        workspace_id: str,
    ) -> None:
        key = self._session_key(session_id)
        state = {
            "session_id": session_id,
            "meeting_id": meeting_id,
            "user_id": user_id,
            "workspace_id": workspace_id,
            "status": "active",
            "created_at": __import__("time").time(),
        }
        await self._r.hset(key, mapping=state)
        await self._r.expire(key, self.SESSION_TTL)
        logger.info("redis_session_created", session_id=session_id)

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        key = self._session_key(session_id)
        data = await self._r.hgetall(key)
        return data if data else None

    async def update_session_status(self, session_id: str, status: str) -> None:
        key = self._session_key(session_id)
        await self._r.hset(key, "status", status)

    async def delete_session(self, session_id: str) -> None:
        for key_fn in [
            self._session_key,
            self._transcript_key,
            self._suggestions_key,
        ]:
            await self._r.delete(key_fn(session_id))

    # ── Transcript buffering ──────────────────

    async def append_transcript_chunk(
        self,
        session_id: str,
        chunk: dict[str, Any],
    ) -> None:
        key = self._transcript_key(session_id)
        await self._r.rpush(key, json.dumps(chunk))
        await self._r.expire(key, self.TRANSCRIPT_TTL)

    async def get_transcript_chunks(
        self,
        session_id: str,
        start: int = 0,
        end: int = -1,
    ) -> list[dict[str, Any]]:
        key = self._transcript_key(session_id)
        raw_chunks = await self._r.lrange(key, start, end)
        return [json.loads(c) for c in raw_chunks]

    async def get_recent_transcript_text(
        self,
        session_id: str,
        last_n: int = 50,
    ) -> str:
        chunks = await self.get_transcript_chunks(session_id, -last_n, -1)
        lines = []
        for chunk in chunks:
            speaker = chunk.get("speaker", "Speaker")
            text = chunk.get("text", "").strip()
            if text:
                lines.append(f"{speaker}: {text}")
        return "\n".join(lines)

    # ── Pub/Sub ───────────────────────────────

    async def publish(
        self,
        session_id: str,
        channel: str,
        payload: dict[str, Any],
    ) -> None:
        channel_key = self._channel_key(session_id, channel)
        await self._r.publish(channel_key, json.dumps(payload))

    @asynccontextmanager
    async def subscribe(
        self,
        session_id: str,
        channel: str,
    ) -> AsyncGenerator[PubSub, None]:
        pubsub = self._r.pubsub()
        channel_key = self._channel_key(session_id, channel)
        await pubsub.subscribe(channel_key)
        try:
            yield pubsub
        finally:
            await pubsub.unsubscribe(channel_key)
            await pubsub.aclose()

    # ── Suggestions cache ─────────────────────

    async def cache_suggestion(
        self,
        session_id: str,
        suggestion: dict[str, Any],
        ttl: int = 300,
    ) -> None:
        key = self._suggestions_key(session_id)
        await self._r.set(key, json.dumps(suggestion), ex=ttl)

    async def get_cached_suggestion(
        self,
        session_id: str,
    ) -> dict[str, Any] | None:
        key = self._suggestions_key(session_id)
        raw = await self._r.get(key)
        return json.loads(raw) if raw else None

    # ── Rate limiting ─────────────────────────

    async def check_rate_limit(
        self,
        identifier: str,
        limit: int,
        window_seconds: int = 60,
    ) -> tuple[bool, int]:
        key = f"{self.PREFIX}:ratelimit:{identifier}"
        pipe = self._r.pipeline()
        pipe.incr(key)
        pipe.expire(key, window_seconds)
        results = await pipe.execute()
        current_count = results[0]
        allowed = current_count <= limit
        return allowed, current_count
