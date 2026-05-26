"""
Garage Meeting Copilot — Main FastAPI Application (updated)
Includes all routers, middleware, and lifespan management.
"""
from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Query, Request, WebSocket, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import ORJSONResponse
from pydantic import BaseModel

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.database import AsyncSessionLocal, check_db_connection, get_db
from app.core.logging import configure_logging, get_logger
from app.core.redis import RedisStreamState, check_redis_connection, get_redis
from app.middleware.garage_auth import GarageAuthContext, require_garage_auth
from app.middleware.rate_limit import RateLimitMiddleware
from app.repositories.copilot_repo import (
    ActionItemRepository,
    AIInteractionRepository,
    MeetingSessionRepository,
    SummaryRepository,
    TranscriptRepository,
)
from app.schemas.copilot import (
    ActionItemSchema,
    HealthResponse,
    IngestTranscriptRequest,
    SessionCreateRequest,
    SessionEndRequest,
    SessionResponse,
    SummaryResponse,
    TranscriptChunkSchema,
)
from app.services.ai.langgraph_pipeline import SuggestionPipeline
from app.services.ai.workspace_context import workspace_context_engine
from app.services.memory.qdrant_retriever import qdrant_retriever
from app.services.ocr.screen_ocr import screen_ocr_pipeline
from app.gateway import copilot_websocket

configure_logging()
logger = get_logger(__name__)
settings = get_settings()

_start_time = time.monotonic()
_suggestion_pipeline = SuggestionPipeline()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("meeting_ai_service_starting")
    await qdrant_retriever.ensure_collections()
    logger.info("meeting_ai_service_ready")
    yield
    logger.info("meeting_ai_service_shutting_down")


app = FastAPI(
    title="Garage Meeting Copilot — AI Service",
    description="Enterprise realtime AI meeting copilot subsystem for the Garage ecosystem.",
    version="1.0.0",
    default_response_class=ORJSONResponse,
    lifespan=lifespan,
    docs_url="/api/docs" if settings.environment != "production" else None,
    redoc_url="/api/redoc" if settings.environment != "production" else None,
)

# ── Middleware stack ───────────────────────────────────────────────────────────

app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.allowed_origins.split(",")],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    expose_headers=["X-RateLimit-Limit", "X-RateLimit-Remaining"],
)
app.add_middleware(
    RateLimitMiddleware,
    requests_per_minute=settings.rate_limit_per_minute,
)


# ── Request ID / timing middleware ────────────────────────────────────────────

@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    start = time.monotonic()
    response = await call_next(request)
    latency_ms = int((time.monotonic() - start) * 1000)
    logger.info(
        "http_request",
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        latency_ms=latency_ms,
    )
    response.headers["X-Response-Time-Ms"] = str(latency_ms)
    return response


# ── Include routers ────────────────────────────────────────────────────────────

app.include_router(api_router)

# ── WebSocket (realtime gateway) ──────────────────────────────────────────────

app.add_api_websocket_route("/ws/copilot", copilot_websocket)


# ── Health check ──────────────────────────────────────────────────────────────

@app.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check() -> HealthResponse:
    db_ok = await check_db_connection()
    redis_ok = await check_redis_connection()
    qdrant_ok = await qdrant_retriever.check_connection()
    all_ok = db_ok and redis_ok and qdrant_ok

    return HealthResponse(
        status="ok" if all_ok else "degraded",
        service="meeting-ai-service",
        version="1.0.0",
        checks={
            "database": db_ok,
            "redis": redis_ok,
            "qdrant": qdrant_ok,
        },
        uptime_seconds=time.monotonic() - _start_time,
    )


# ── Session Endpoints ─────────────────────────────────────────────────────────

@app.post(
    "/api/v1/copilot/sessions",
    response_model=SessionResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Sessions"],
)
async def create_session(
    body: SessionCreateRequest,
    auth: GarageAuthContext = Depends(require_garage_auth),
    db=Depends(get_db),
) -> SessionResponse:
    """Create a new copilot session for a Garage meeting."""
    repo = MeetingSessionRepository(db)

    existing = await repo.get_active_for_user(
        user_id=auth.user_id,
        garage_meeting_id=body.garage_meeting_id,
    )
    if existing:
        return SessionResponse.model_validate(existing)

    session = await repo.create(
        garage_meeting_id=body.garage_meeting_id,
        user_id=auth.user_id,
        organization_id=auth.organization_id,
        workspace_id=body.workspace_id or auth.workspace_id,
    )

    redis_state = RedisStreamState(get_redis())
    await redis_state.create_session(
        session_id=session.id,
        meeting_id=body.garage_meeting_id,
        user_id=auth.user_id,
        workspace_id=body.workspace_id or auth.workspace_id or "",
    )

    logger.info(
        "copilot_session_created",
        session_id=session.id,
        garage_meeting_id=body.garage_meeting_id,
        user_id=auth.user_id,
    )

    # Fire-and-forget: prefetch meeting context from contacts-backend and
    # cache under meeting_ctx:{session_id} so pipelines can read it.
    async def _prefetch_meeting_ctx(session_id: str, room_name: str, token: str) -> None:
        try:
            ctx = await workspace_context_engine.get_meeting_context(room_name, token)
            if ctx:
                await redis_state.cache_suggestion(
                    f"meeting_ctx:{session_id}", ctx, ttl=3600
                )
        except Exception as e:
            logger.warning("meeting_ctx_prefetch_failed", error=str(e))

    asyncio.create_task(
        _prefetch_meeting_ctx(session.id, body.garage_meeting_id, auth.raw_token)
    )

    return SessionResponse.model_validate(session)


@app.get(
    "/api/v1/copilot/sessions/{session_id}",
    response_model=SessionResponse,
    tags=["Sessions"],
)
async def get_session(
    session_id: str,
    auth: GarageAuthContext = Depends(require_garage_auth),
    db=Depends(get_db),
) -> SessionResponse:
    repo = MeetingSessionRepository(db)
    session = await repo.get_by_id(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.user_id != auth.user_id and not auth.is_admin:
        raise HTTPException(status_code=403, detail="Access denied")
    return SessionResponse.model_validate(session)


@app.post(
    "/api/v1/copilot/sessions/{session_id}/end",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    tags=["Sessions"],
)
async def end_session(
    session_id: str,
    auth: GarageAuthContext = Depends(require_garage_auth),
    db=Depends(get_db),
) -> None:
    repo = MeetingSessionRepository(db)
    session = await repo.get_by_id(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.user_id != auth.user_id and not auth.is_admin:
        raise HTTPException(status_code=403, detail="Access denied")

    await repo.end_session(session_id)
    redis_state = RedisStreamState(get_redis())
    await redis_state.update_session_status(session_id, "ended")

    logger.info("copilot_session_ended", session_id=session_id)


# ── Transcript Endpoints ───────────────────────────────────────────────────────

@app.post(
    "/api/v1/copilot/sessions/{session_id}/transcript",
    response_model=TranscriptChunkSchema,
    status_code=status.HTTP_201_CREATED,
    tags=["Transcripts"],
)
async def ingest_transcript_chunk(
    session_id: str,
    body: IngestTranscriptRequest,
    auth: GarageAuthContext = Depends(require_garage_auth),
    db=Depends(get_db),
) -> TranscriptChunkSchema:
    session_repo = MeetingSessionRepository(db)
    session = await session_repo.get_by_id(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.user_id != auth.user_id and not auth.is_admin:
        raise HTTPException(status_code=403, detail="Access denied")

    transcript_repo = TranscriptRepository(db)
    existing = await transcript_repo.get_session_transcript(session_id, only_final=False)
    sequence_number = len(existing)

    chunk = await transcript_repo.create(
        session_id=session_id,
        sequence_number=sequence_number,
        text=body.text,
        speaker_label=body.speaker_label,
        start_time=body.start_time,
        end_time=body.end_time,
        confidence=body.confidence,
        is_final=body.is_final,
    )
    await db.commit()
    return TranscriptChunkSchema.model_validate(chunk)


@app.get(
    "/api/v1/copilot/sessions/{session_id}/transcript",
    response_model=list[TranscriptChunkSchema],
    tags=["Transcripts"],
)
async def get_transcript(
    session_id: str,
    only_final: bool = True,
    limit: int = 500,
    auth: GarageAuthContext = Depends(require_garage_auth),
    db=Depends(get_db),
) -> list[TranscriptChunkSchema]:
    session_repo = MeetingSessionRepository(db)
    session = await session_repo.get_by_id(session_id)
    if not session or (session.user_id != auth.user_id and not auth.is_admin):
        raise HTTPException(status_code=403, detail="Access denied")

    transcript_repo = TranscriptRepository(db)
    chunks = await transcript_repo.get_session_transcript(
        session_id, only_final=only_final, limit=limit
    )
    return [TranscriptChunkSchema.model_validate(c) for c in chunks]


# ── Summary Endpoints ─────────────────────────────────────────────────────────

@app.get(
    "/api/v1/copilot/sessions/{session_id}/summaries",
    response_model=list[SummaryResponse],
    tags=["Summaries"],
)
async def get_summaries(
    session_id: str,
    auth: GarageAuthContext = Depends(require_garage_auth),
    db=Depends(get_db),
) -> list[SummaryResponse]:
    session_repo = MeetingSessionRepository(db)
    session = await session_repo.get_by_id(session_id)
    if not session or (session.user_id != auth.user_id and not auth.is_admin):
        raise HTTPException(status_code=403, detail="Access denied")

    summary_repo = SummaryRepository(db)
    summaries = await summary_repo.list_for_session(session_id)
    return [SummaryResponse.model_validate(s) for s in summaries]


# ── Action Item Endpoints ─────────────────────────────────────────────────────

@app.get(
    "/api/v1/copilot/sessions/{session_id}/action-items",
    response_model=list[ActionItemSchema],
    tags=["Action Items"],
)
async def get_action_items(
    session_id: str,
    status_filter: str | None = None,
    auth: GarageAuthContext = Depends(require_garage_auth),
    db=Depends(get_db),
) -> list[ActionItemSchema]:
    session_repo = MeetingSessionRepository(db)
    session = await session_repo.get_by_id(session_id)
    if not session or (session.user_id != auth.user_id and not auth.is_admin):
        raise HTTPException(status_code=403, detail="Access denied")

    action_repo = ActionItemRepository(db)
    items = await action_repo.list_for_session(session_id, status=status_filter)
    return [ActionItemSchema.model_validate(i) for i in items]


# ── Semantic Search ────────────────────────────────────────────────────────────

@app.get("/api/v1/copilot/sessions/{session_id}/search", tags=["Search"])
async def semantic_search(
    session_id: str,
    q: str,
    limit: int = 10,
    auth: GarageAuthContext = Depends(require_garage_auth),
    db=Depends(get_db),
) -> dict:
    if not q.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    session_repo = MeetingSessionRepository(db)
    session = await session_repo.get_by_id(session_id)
    if not session or (session.user_id != auth.user_id and not auth.is_admin):
        raise HTTPException(status_code=403, detail="Access denied")

    results = await qdrant_retriever.search_transcript(
        query=q,
        session_id=session_id,
        limit=limit,
    )

    return {"query": q, "results": results, "count": len(results)}


# ── AI Suggestions ────────────────────────────────────────────────────────────

class SuggestRequest(BaseModel):
    transcript_window: str
    context: str = ""


@app.post(
    "/api/v1/copilot/sessions/{session_id}/suggest",
    tags=["AI"],
)
async def request_suggestions(
    session_id: str,
    body: SuggestRequest,
    auth: GarageAuthContext = Depends(require_garage_auth),
    db=Depends(get_db),
) -> dict:
    session_repo = MeetingSessionRepository(db)
    session = await session_repo.get_by_id(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.user_id != auth.user_id and not auth.is_admin:
        raise HTTPException(status_code=403, detail="Access denied")

    suggestions = await _suggestion_pipeline.generate(
        session_id=session_id,
        recent_transcript=body.transcript_window,
        screen_context=body.context,
        user_id=auth.user_id,
    )
    return {"session_id": session_id, "suggestions": suggestions}


# ── Screen OCR ────────────────────────────────────────────────────────────────

class ScreenRequest(BaseModel):
    image_data: str  # base64-encoded PNG/JPEG


@app.post(
    "/api/v1/copilot/sessions/{session_id}/screen",
    tags=["OCR"],
)
async def ingest_screen_context(
    session_id: str,
    body: ScreenRequest,
    auth: GarageAuthContext = Depends(require_garage_auth),
    db=Depends(get_db),
) -> dict:
    session_repo = MeetingSessionRepository(db)
    session = await session_repo.get_by_id(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.user_id != auth.user_id and not auth.is_admin:
        raise HTTPException(status_code=403, detail="Access denied")

    result = await screen_ocr_pipeline.process_screenshot(
        image_data=body.image_data,
        session_id=session_id,
    )
    return {
        "session_id": session_id,
        "extracted_text": result.extracted_text,
        "cleaned_text": result.cleaned_text,
        "word_count": result.word_count,
        "confidence": result.confidence,
        "application_hint": result.application_hint,
    }
