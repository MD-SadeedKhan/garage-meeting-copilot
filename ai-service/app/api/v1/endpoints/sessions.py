"""
Garage Meeting Copilot — Session Management Endpoints
Create, retrieve, and manage copilot sessions.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.core.database import get_db
from app.middleware.garage_auth import GarageAuthContext, require_garage_auth
from app.repositories.copilot_repo import (
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

    class Config:
        from_attributes = True


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


@router.post("/sessions", response_model=SessionResponse, status_code=201)
async def create_session(
    req: CreateSessionRequest,
    auth: GarageAuthContext = Depends(require_garage_auth),
    db=Depends(get_db),
) -> SessionResponse:
    """Create a new copilot session for a meeting."""
    repo = MeetingSessionRepository(db)
    session = await repo.create(
        garage_meeting_id=req.garage_meeting_id,
        user_id=auth.user_id,
        organization_id=auth.organization_id,
        workspace_id=req.workspace_id or auth.workspace_id,
    )
    await db.commit()
    return SessionResponse.model_validate(session)


@router.get("/sessions/{session_id}", response_model=SessionResponse)
async def get_session(
    session_id: str,
    auth: GarageAuthContext = Depends(require_garage_auth),
    db=Depends(get_db),
) -> SessionResponse:
    """Retrieve a session by ID."""
    repo = MeetingSessionRepository(db)
    session = await repo.get_by_id(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.user_id != auth.user_id and not auth.is_admin:
        raise HTTPException(status_code=403, detail="Access denied")
    return SessionResponse.model_validate(session)


@router.post("/sessions/{session_id}/transcript", response_model=TranscriptChunkResponse, status_code=201)
async def ingest_transcript(
    session_id: str,
    req: TranscriptChunkRequest,
    auth: GarageAuthContext = Depends(require_garage_auth),
    db=Depends(get_db),
) -> TranscriptChunkResponse:
    """Add a transcript chunk to a session."""
    session_repo = MeetingSessionRepository(db)
    session = await session_repo.get_by_id(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.user_id != auth.user_id and not auth.is_admin:
        raise HTTPException(status_code=403, detail="Access denied")

    transcript_repo = TranscriptRepository(db)
    chunk = await transcript_repo.create(
        session_id=session_id,
        text=req.text,
        speaker_label=req.speaker_label,
        start_time=req.start_time,
        end_time=req.end_time,
        confidence=req.confidence,
        is_final=req.is_final,
    )
    await db.commit()
    return TranscriptChunkResponse.model_validate(chunk)


@router.get("/sessions/{session_id}/transcript", response_model=list[TranscriptChunkResponse])
async def get_transcript(
    session_id: str,
    auth: GarageAuthContext = Depends(require_garage_auth),
    db=Depends(get_db),
) -> list[TranscriptChunkResponse]:
    """Retrieve all transcript chunks for a session."""
    session_repo = MeetingSessionRepository(db)
    session = await session_repo.get_by_id(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.user_id != auth.user_id and not auth.is_admin:
        raise HTTPException(status_code=403, detail="Access denied")

    transcript_repo = TranscriptRepository(db)
    chunks = await transcript_repo.list_for_session(session_id)
    return [TranscriptChunkResponse.model_validate(chunk) for chunk in chunks]
