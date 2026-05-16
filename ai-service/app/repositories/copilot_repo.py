"""
Garage Meeting Copilot — Session & Transcript Repository
Data access layer following the repository pattern.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.logging import get_logger
from app.models.copilot import (
    AIInteraction,
    ActionItem,
    MeetingSession,
    MeetingSummary,
    ScreenContext,
    TranscriptChunk,
)

logger = get_logger(__name__)


class MeetingSessionRepository:
    """CRUD operations for MeetingSession entities."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def create(
        self,
        garage_meeting_id: str,
        user_id: str,
        organization_id: str,
        workspace_id: str | None = None,
    ) -> MeetingSession:
        session = MeetingSession(
            id=str(uuid.uuid4()),
            garage_meeting_id=garage_meeting_id,
            user_id=user_id,
            organization_id=organization_id,
            workspace_id=workspace_id,
            status="active",
        )
        self._db.add(session)
        await self._db.flush()
        logger.info(
            "session_created",
            session_id=session.id,
            garage_meeting_id=garage_meeting_id,
        )
        return session

    async def get_by_id(self, session_id: str) -> MeetingSession | None:
        result = await self._db.execute(
            select(MeetingSession).where(MeetingSession.id == session_id)
        )
        return result.scalar_one_or_none()

    async def get_active_for_user(
        self,
        user_id: str,
        garage_meeting_id: str,
    ) -> MeetingSession | None:
        result = await self._db.execute(
            select(MeetingSession).where(
                MeetingSession.user_id == user_id,
                MeetingSession.garage_meeting_id == garage_meeting_id,
                MeetingSession.status == "active",
            )
        )
        return result.scalar_one_or_none()

    async def end_session(self, session_id: str) -> None:
        await self._db.execute(
            update(MeetingSession)
            .where(MeetingSession.id == session_id)
            .values(
                status="ended",
                ended_at=datetime.now(timezone.utc),
            )
        )

    async def get_with_relations(self, session_id: str) -> MeetingSession | None:
        result = await self._db.execute(
            select(MeetingSession)
            .options(
                selectinload(MeetingSession.transcripts),
                selectinload(MeetingSession.summaries),
                selectinload(MeetingSession.action_items),
            )
            .where(MeetingSession.id == session_id)
        )
        return result.scalar_one_or_none()


class TranscriptRepository:
    """CRUD operations for TranscriptChunk entities."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def create(
        self,
        session_id: str,
        sequence_number: int,
        text: str,
        speaker_label: str | None,
        start_time: float,
        end_time: float,
        confidence: float,
        is_final: bool,
        qdrant_point_id: str | None = None,
    ) -> TranscriptChunk:
        chunk = TranscriptChunk(
            id=str(uuid.uuid4()),
            session_id=session_id,
            sequence_number=sequence_number,
            text=text,
            speaker_label=speaker_label,
            start_time=start_time,
            end_time=end_time,
            confidence=confidence,
            is_final=is_final,
            qdrant_point_id=qdrant_point_id,
        )
        self._db.add(chunk)
        await self._db.flush()
        return chunk

    async def update_qdrant_id(
        self,
        chunk_id: str,
        qdrant_point_id: str,
    ) -> None:
        await self._db.execute(
            update(TranscriptChunk)
            .where(TranscriptChunk.id == chunk_id)
            .values(qdrant_point_id=qdrant_point_id)
        )

    async def get_session_transcript(
        self,
        session_id: str,
        only_final: bool = True,
        limit: int | None = None,
    ) -> list[TranscriptChunk]:
        q = (
            select(TranscriptChunk)
            .where(TranscriptChunk.session_id == session_id)
            .order_by(TranscriptChunk.sequence_number)
        )
        if only_final:
            q = q.where(TranscriptChunk.is_final == True)
        if limit:
            q = q.limit(limit)

        result = await self._db.execute(q)
        return list(result.scalars().all())

    async def get_transcript_text(
        self,
        session_id: str,
        last_n: int | None = None,
    ) -> str:
        q = (
            select(TranscriptChunk)
            .where(
                TranscriptChunk.session_id == session_id,
                TranscriptChunk.is_final == True,
            )
            .order_by(TranscriptChunk.sequence_number)
        )
        if last_n:
            # Get last N final chunks
            subq = (
                select(TranscriptChunk.id)
                .where(
                    TranscriptChunk.session_id == session_id,
                    TranscriptChunk.is_final == True,
                )
                .order_by(TranscriptChunk.sequence_number.desc())
                .limit(last_n)
                .subquery()
            )
            q = (
                select(TranscriptChunk)
                .where(TranscriptChunk.id.in_(select(subq)))
                .order_by(TranscriptChunk.sequence_number)
            )

        result = await self._db.execute(q)
        chunks = result.scalars().all()

        lines = []
        for chunk in chunks:
            speaker = chunk.speaker_label or "Speaker"
            lines.append(f"{speaker}: {chunk.text}")
        return "\n".join(lines)

    async def count_chunks(self, session_id: str) -> int:
        result = await self._db.execute(
            select(func.count(TranscriptChunk.id)).where(
                TranscriptChunk.session_id == session_id,
                TranscriptChunk.is_final == True,
            )
        )
        return result.scalar_one() or 0


class SummaryRepository:
    """CRUD operations for MeetingSummary entities."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def create(
        self,
        session_id: str,
        content: str,
        summary_type: str = "rolling",
        transcript_range_start: int = 0,
        transcript_range_end: int = 0,
        token_count: int = 0,
        s3_key: str | None = None,
    ) -> MeetingSummary:
        summary = MeetingSummary(
            id=str(uuid.uuid4()),
            session_id=session_id,
            content=content,
            summary_type=summary_type,
            transcript_range_start=transcript_range_start,
            transcript_range_end=transcript_range_end,
            token_count=token_count,
            s3_key=s3_key,
        )
        self._db.add(summary)
        await self._db.flush()
        return summary

    async def get_latest(
        self,
        session_id: str,
        summary_type: str = "rolling",
    ) -> MeetingSummary | None:
        result = await self._db.execute(
            select(MeetingSummary)
            .where(
                MeetingSummary.session_id == session_id,
                MeetingSummary.summary_type == summary_type,
            )
            .order_by(MeetingSummary.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_for_session(self, session_id: str) -> list[MeetingSummary]:
        result = await self._db.execute(
            select(MeetingSummary)
            .where(MeetingSummary.session_id == session_id)
            .order_by(MeetingSummary.created_at.desc())
        )
        return list(result.scalars().all())


class ActionItemRepository:
    """CRUD operations for ActionItem entities."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def bulk_upsert(
        self,
        session_id: str,
        items: list[dict[str, Any]],
    ) -> list[ActionItem]:
        """Create action items from AI extraction results."""
        created = []
        for item_data in items:
            item = ActionItem(
                id=str(uuid.uuid4()),
                session_id=session_id,
                title=item_data.get("title", ""),
                description=item_data.get("description"),
                assignee=item_data.get("assignee"),
                due_date=item_data.get("due_date"),
                priority=item_data.get("priority", "medium"),
                confidence_score=item_data.get("confidence_score", 0.9),
                status="open",
            )
            self._db.add(item)
            created.append(item)
        await self._db.flush()
        return created

    async def list_for_session(
        self,
        session_id: str,
        status: str | None = None,
    ) -> list[ActionItem]:
        q = select(ActionItem).where(ActionItem.session_id == session_id)
        if status:
            q = q.where(ActionItem.status == status)
        q = q.order_by(ActionItem.created_at.desc())
        result = await self._db.execute(q)
        return list(result.scalars().all())


class AIInteractionRepository:
    """CRUD operations for AIInteraction entities."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def create(
        self,
        session_id: str,
        interaction_type: str,
        ai_response: str,
        user_message: str | None = None,
        context_chunks_used: list[str] | None = None,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        latency_ms: int = 0,
    ) -> AIInteraction:
        interaction = AIInteraction(
            id=str(uuid.uuid4()),
            session_id=session_id,
            interaction_type=interaction_type,
            user_message=user_message,
            ai_response=ai_response,
            context_chunks_used=context_chunks_used or [],
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=latency_ms,
        )
        self._db.add(interaction)
        await self._db.flush()
        return interaction
