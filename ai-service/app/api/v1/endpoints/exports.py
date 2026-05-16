"""
Garage Meeting Copilot — Export Endpoints
Generate and deliver meeting exports: transcripts, summaries, action items.
"""
from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from app.core.database import get_db
from app.middleware.garage_auth import GarageAuthContext, require_garage_auth
from app.repositories.copilot_repo import (
    ActionItemRepository,
    MeetingSessionRepository,
    SummaryRepository,
    TranscriptRepository,
)
from app.services.storage.s3_storage import s3_storage

router = APIRouter(prefix="/api/v1/copilot", tags=["Exports"])


class ExportResponse(BaseModel):
    session_id: str
    export_type: str
    s3_key: str | None
    content: str | None
    generated_at: datetime


@router.get(
    "/sessions/{session_id}/export/transcript",
    response_class=PlainTextResponse,
    tags=["Exports"],
)
async def export_transcript(
    session_id: str,
    format: str = "txt",
    auth: GarageAuthContext = Depends(require_garage_auth),
    db=Depends(get_db),
) -> str:
    """Export full session transcript as plain text."""
    session_repo = MeetingSessionRepository(db)
    session = await session_repo.get_by_id(session_id)
    if not session or (session.user_id != auth.user_id and not auth.is_admin):
        raise HTTPException(status_code=403, detail="Access denied")

    transcript_repo = TranscriptRepository(db)
    text = await transcript_repo.get_transcript_text(session_id)

    header = (
        f"Garage Meeting Copilot — Transcript Export\n"
        f"Session: {session_id}\n"
        f"Meeting: {session.garage_meeting_id}\n"
        f"Started: {session.started_at.isoformat()}\n"
        f"{'='*60}\n\n"
    )

    return header + text


@router.get(
    "/sessions/{session_id}/export/summary",
    response_class=PlainTextResponse,
    tags=["Exports"],
)
async def export_summary(
    session_id: str,
    auth: GarageAuthContext = Depends(require_garage_auth),
    db=Depends(get_db),
) -> str:
    """Export the latest meeting summary."""
    session_repo = MeetingSessionRepository(db)
    session = await session_repo.get_by_id(session_id)
    if not session or (session.user_id != auth.user_id and not auth.is_admin):
        raise HTTPException(status_code=403, detail="Access denied")

    summary_repo = SummaryRepository(db)
    summary = await summary_repo.get_latest(session_id)

    if not summary:
        raise HTTPException(status_code=404, detail="No summary available yet")

    return summary.content


@router.get(
    "/sessions/{session_id}/export/action-items",
    tags=["Exports"],
)
async def export_action_items(
    session_id: str,
    auth: GarageAuthContext = Depends(require_garage_auth),
    db=Depends(get_db),
) -> dict:
    """Export action items as structured JSON."""
    session_repo = MeetingSessionRepository(db)
    session = await session_repo.get_by_id(session_id)
    if not session or (session.user_id != auth.user_id and not auth.is_admin):
        raise HTTPException(status_code=403, detail="Access denied")

    action_repo = ActionItemRepository(db)
    items = await action_repo.list_for_session(session_id)

    return {
        "session_id": session_id,
        "garage_meeting_id": session.garage_meeting_id,
        "exported_at": datetime.utcnow().isoformat(),
        "total_items": len(items),
        "items": [
            {
                "title": item.title,
                "description": item.description,
                "assignee": item.assignee,
                "due_date": item.due_date,
                "priority": item.priority,
                "status": item.status,
                "confidence_score": item.confidence_score,
                "created_at": item.created_at.isoformat(),
            }
            for item in items
        ],
    }


@router.post(
    "/sessions/{session_id}/export/s3",
    tags=["Exports"],
)
async def export_to_s3(
    session_id: str,
    background_tasks: BackgroundTasks,
    auth: GarageAuthContext = Depends(require_garage_auth),
    db=Depends(get_db),
) -> dict:
    """
    Trigger a background export of all artifacts to S3.
    Returns immediately; export runs async.
    """
    session_repo = MeetingSessionRepository(db)
    session = await session_repo.get_by_id(session_id)
    if not session or (session.user_id != auth.user_id and not auth.is_admin):
        raise HTTPException(status_code=403, detail="Access denied")

    async def do_export():
        transcript_repo = TranscriptRepository(db)
        summary_repo = SummaryRepository(db)
        action_repo = ActionItemRepository(db)

        transcript_text = await transcript_repo.get_transcript_text(session_id)
        summary = await summary_repo.get_latest(session_id)
        actions = await action_repo.list_for_session(session_id)

        if transcript_text:
            await s3_storage.upload_transcript_export(
                session_id=session_id,
                organization_id=session.organization_id,
                garage_meeting_id=session.garage_meeting_id,
                transcript_text=transcript_text,
            )

        if summary:
            await s3_storage.upload_summary(
                session_id=session_id,
                organization_id=session.organization_id,
                garage_meeting_id=session.garage_meeting_id,
                summary_content=summary.content,
            )

        if actions:
            await s3_storage.upload_action_items_json(
                session_id=session_id,
                organization_id=session.organization_id,
                garage_meeting_id=session.garage_meeting_id,
                action_items=[
                    {
                        "title": a.title,
                        "description": a.description,
                        "assignee": a.assignee,
                        "priority": a.priority,
                        "status": a.status,
                    }
                    for a in actions
                ],
            )

    background_tasks.add_task(do_export)

    return {
        "session_id": session_id,
        "status": "export_queued",
        "message": "Artifacts are being exported to S3 in the background.",
    }
