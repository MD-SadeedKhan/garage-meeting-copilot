"""
Garage Meeting Copilot — Workspace Context Engine
Fetches and caches Garage workspace context for AI enrichment.
"""
from __future__ import annotations

import json
from typing import Any

from app.core.logging import get_logger
from app.core.redis import RedisStreamState, get_redis
from app.middleware.garage_auth import GarageAPIClient

logger = get_logger(__name__)

WORKSPACE_CONTEXT_TTL = 300  # 5 minutes


class WorkspaceContextEngine:
    """
    Fetches workspace context from Garage APIs and caches in Redis.
    Provides enriched context for the AI pipeline.
    """

    def __init__(self) -> None:
        self._client = GarageAPIClient()

    async def get_workspace_context(
        self,
        workspace_id: str,
        token: str,
        use_cache: bool = True,
    ) -> dict[str, Any]:
        """
        No-op: workspace context is no longer fetched separately.
        Retained to avoid breaking callers.
        """
        return {}

    async def get_meeting_context(
        self,
        meeting_id: str,
        token: str,
    ) -> dict[str, Any]:
        """
        Retrieve meeting context from Garage API with Redis caching.
        """
        redis_state = RedisStreamState(get_redis())
        cache_key = f"meeting_ctx:{meeting_id}"

        cached = await redis_state.get_cached_suggestion(cache_key)
        if cached:
            return cached

        try:
            context = await self._client.get_meeting_context(meeting_id, token)
            await redis_state.cache_suggestion(cache_key, context, ttl=60)
            return context
        except Exception as e:
            logger.warning(
                "meeting_context_fetch_failed",
                meeting_id=meeting_id,
                error=str(e),
            )
            return {}

    def format_for_ai(self, workspace_ctx: dict[str, Any]) -> str:
        """Format workspace context as a human-readable string for AI prompts."""
        if not workspace_ctx:
            return ""

        parts = []
        if name := workspace_ctx.get("name"):
            parts.append(f"Workspace: {name}")
        if description := workspace_ctx.get("description"):
            parts.append(f"Description: {description}")
        if tags := workspace_ctx.get("tags"):
            parts.append(f"Tags: {', '.join(tags)}")

        return "\n".join(parts) if parts else ""


# Module-level singleton
workspace_context_engine = WorkspaceContextEngine()
