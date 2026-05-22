"""
Garage Meeting Copilot — Session Management Endpoints
Create, retrieve, and manage copilot sessions.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field

from app.core.database import get_db
from app.middleware.garage_auth import GarageAuthContext, require_garage_auth
from app.repositories.copilot_repo import (
    AIInteractionRepository,
    MeetingSessionRepository,
    TranscriptRepository,
)

router = APIRouter(prefix="/api/v1/copilot", tags=["Sessions"])


class CreateSessionRequest(BaseModel):
    garage_meeting_id: str
    workspace_id: str | None = None


class SessionResponse(BaseModel):
    id: str
    garage_meeting_id: str
    user_id: str
    organization_id: str
    workspace_id: str | None
    status: str
    started_at: datetime
    ended_at: datetime | None = None
    title: str | None = None

    class Config:
        from_attributes = True


class SessionListItem(BaseModel):
    id: str
    title: str | None
    garage_meeting_id: str
    status: str
    started_at: datetime
    ended_at: datetime | None
    duration_seconds: int | None
    message_count: int


class SessionListResponse(BaseModel):
    items: list[SessionListItem]
    total: int


class RenameSessionRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class ChatMessage(BaseModel):
    id: str
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime


class ChatHistoryResponse(BaseModel):
    items: list[ChatMessage]


class TranscriptChunkRequest(BaseModel):
    text: str
    speaker_label: str | None = None
    start_time: float
    end_time: float
    confidence: float = 1.0
    is_final: bool = True


class TranscriptChunkResponse(BaseModel):
    id: str
    session_id: str
    text: str
    speaker_label: str | None
    start_time: float
    end_time: float
    confidence: float
    is_final: bool
    created_at: datetime

    class Config:
        from_attributes = True


@router.get("/sessions", response_model=SessionListResponse)
async def list_sessions(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    status_filter: str | None = Query(None, alias="status"),
    auth: GarageAuthContext = Depends(require_garage_auth),
    db=Depends(get_db),
) -> SessionListResponse:
    """List the current user's copilot sessions."""
    repo = MeetingSessionRepository(db)
    sessions, total = await repo.list_for_user(
        user_id=auth.user_id,
        limit=limit,
        offset=offset,
        status_filter=status_filter,
    )

    items: list[SessionListItem] = []
    for s in sessions:
        duration: int | None = None
        if s.ended_at and s.started_at:
            duration = int((s.ended_at - s.started_at).total_seconds())
        items.append(
            SessionListItem(
                id=s.id,
                title=s.title,
                garage_meeting_id=s.garage_meeting_id,
                status=s.status,
                started_at=s.started_at,
                ended_at=s.ended_at,
                duration_seconds=duration,
                message_count=getattr(s, "_message_count", 0),
            )
        )
    return SessionListResponse(items=items, total=total)


# POST /sessions, GET /sessions/{id}, and POST/GET transcript handlers
# live directly on the `app` object in `main.py`. Keeping the router
# scoped to the NEW endpoints (list/rename/delete/chat) avoids
# double-registration when this router is mounted via api_router.


@router.patch("/sessions/{session_id}", response_model=SessionResponse)
async def rename_session(
    session_id: str,
    req: RenameSessionRequest,
    auth: GarageAuthContext = Depends(require_garage_auth),
    db=Depends(get_db),
) -> SessionResponse:
    """Rename a session."""
    repo = MeetingSessionRepository(db)
    session = await repo.get_by_id(session_id)
    if not session or session.user_id != auth.user_id:
        raise HTTPException(status_code=404, detail="Session not found")

    title = req.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="Title cannot be empty")
    if len(title) > 200:
        title = title[:200]

    updated = await repo.rename(session_id, title)
    await db.commit()
    return SessionResponse.model_validate(updated)


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(
    session_id: str,
    auth: GarageAuthContext = Depends(require_garage_auth),
    db=Depends(get_db),
) -> Response:
    """Delete a session and all child rows (cascade)."""
    repo = MeetingSessionRepository(db)
    session = await repo.get_by_id(session_id)
    if not session or session.user_id != auth.user_id:
        raise HTTPException(status_code=404, detail="Session not found")

    # TODO: best-effort delete corresponding Qdrant points for transcript chunks.
    # Skipping for v1 — Qdrant garbage will accumulate.
    await repo.delete(session)
    await db.commit()
    return Response(status_code=204)


@router.get("/sessions/{session_id}/chat", response_model=ChatHistoryResponse)
async def get_chat_history(
    session_id: str,
    auth: GarageAuthContext = Depends(require_garage_auth),
    db=Depends(get_db),
) -> ChatHistoryResponse:
    """Return Ask-panel chat history for a session as a flat user/assistant list."""
    repo = MeetingSessionRepository(db)
    session = await repo.get_by_id(session_id)
    if not session or (session.user_id != auth.user_id and not auth.is_admin):
        raise HTTPException(status_code=404, detail="Session not found")

    interactions_repo = AIInteractionRepository(db)
    interactions = await interactions_repo.list_chat_for_session(session_id)

    items: list[ChatMessage] = []
    for row in interactions:
        if row.user_message:
            items.append(
                ChatMessage(
                    id=f"{row.id}:u",
                    role="user",
                    content=row.user_message,
                    created_at=row.created_at,
                )
            )
        items.append(
            ChatMessage(
                id=f"{row.id}:a",
                role="assistant",
                content=row.ai_response,
                created_at=row.created_at,
            )
        )
    return ChatHistoryResponse(items=items)
