"""
Garage Meeting Copilot — Pydantic Schemas
Request/response validation models for all API endpoints.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


# ── Base ──────────────────────────────────────────────────────────────────────

class CopilotBase(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


# ── Session ───────────────────────────────────────────────────────────────────

class SessionCreateRequest(CopilotBase):
    garage_meeting_id: str = Field(..., description="Garage platform meeting ID")
    workspace_id: str | None = Field(None, description="Optional workspace context")


class SessionResponse(CopilotBase):
    id: str
    garage_meeting_id: str
    user_id: str
    organization_id: str
    workspace_id: str | None
    status: str
    started_at: datetime
    ended_at: datetime | None


class SessionEndRequest(CopilotBase):
    session_id: str


# ── Transcript ────────────────────────────────────────────────────────────────

class IngestTranscriptRequest(CopilotBase):
    text: str
    speaker_label: str | None = None
    start_time: float
    end_time: float
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    is_final: bool = True


class TranscriptChunkSchema(CopilotBase):
    id: str
    session_id: str
    sequence_number: int
    text: str
    speaker_label: str | None
    start_time: float
    end_time: float
    confidence: float
    is_final: bool
    created_at: datetime


class TranscriptStreamEvent(CopilotBase):
    """Emitted over WebSocket for each transcript update."""
    event: Literal["transcript"] = "transcript"
    session_id: str
    chunk_id: str
    text: str
    speaker_label: str | None
    start_time: float
    end_time: float
    is_final: bool
    sequence_number: int


# ── AI Suggestions ────────────────────────────────────────────────────────────

class SuggestionItem(CopilotBase):
    type: Literal["question", "clarification", "fact", "action", "followup"]
    content: str
    confidence: float = Field(ge=0.0, le=1.0)
    context_excerpt: str | None = None


class SuggestionsStreamEvent(CopilotBase):
    """Emitted over WebSocket when new AI suggestions are ready."""
    event: Literal["suggestions"] = "suggestions"
    session_id: str
    suggestions: list[SuggestionItem]
    generated_at: datetime = Field(default_factory=datetime.utcnow)


# ── Summary ───────────────────────────────────────────────────────────────────

class SummaryStreamEvent(CopilotBase):
    """Emitted over WebSocket when rolling summary updates."""
    event: Literal["summary"] = "summary"
    session_id: str
    content: str
    summary_type: str
    transcript_range_start: int
    transcript_range_end: int
    generated_at: datetime = Field(default_factory=datetime.utcnow)


class SummaryResponse(CopilotBase):
    id: str
    session_id: str
    summary_type: str
    content: str
    created_at: datetime


# ── Action Items ──────────────────────────────────────────────────────────────

class ActionItemSchema(CopilotBase):
    id: str
    session_id: str
    title: str
    description: str | None
    assignee: str | None
    due_date: str | None
    priority: Literal["low", "medium", "high", "critical"]
    status: str
    confidence_score: float
    created_at: datetime


class ActionItemsStreamEvent(CopilotBase):
    """Emitted over WebSocket when action items are extracted/updated."""
    event: Literal["action_items"] = "action_items"
    session_id: str
    items: list[ActionItemSchema]
    generated_at: datetime = Field(default_factory=datetime.utcnow)


# ── AI Chat ───────────────────────────────────────────────────────────────────

class ChatMessageRequest(CopilotBase):
    session_id: str
    message: str = Field(..., min_length=1, max_length=4000)
    include_screen_context: bool = False


class ChatStreamToken(CopilotBase):
    """Individual streaming token from the AI chat response."""
    event: Literal["chat_token"] = "chat_token"
    session_id: str
    token: str
    is_final: bool = False


class ChatCompletionEvent(CopilotBase):
    """Final event when chat streaming is complete."""
    event: Literal["chat_complete"] = "chat_complete"
    session_id: str
    full_response: str
    context_chunks_used: list[str]
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int


# ── Screen Context ────────────────────────────────────────────────────────────

class ScreenContextUpload(CopilotBase):
    session_id: str
    extracted_text: str
    application_name: str | None = None
    window_title: str | None = None


class ScreenContextResponse(CopilotBase):
    id: str
    session_id: str
    extracted_text: str
    application_name: str | None
    window_title: str | None
    captured_at: datetime


# ── Audio Stream ──────────────────────────────────────────────────────────────

class AudioStreamConfig(CopilotBase):
    session_id: str
    sample_rate: int = Field(default=16000, ge=8000, le=48000)
    channels: int = Field(default=1, ge=1, le=2)
    encoding: Literal["linear16", "mulaw", "opus"] = "linear16"
    source: Literal["microphone", "system", "mixed"] = "microphone"


# ── WebSocket Events ──────────────────────────────────────────────────────────

class WSConnectPayload(CopilotBase):
    type: Literal["connect"] = "connect"
    session_id: str
    token: str


class WSAudioChunk(CopilotBase):
    type: Literal["audio"] = "audio"
    session_id: str
    data: str  # base64-encoded PCM audio
    sequence: int
    source: Literal["microphone", "system", "mixed"] = "microphone"


class WSChatMessage(CopilotBase):
    type: Literal["chat"] = "chat"
    session_id: str
    message: str


class WSScreenContext(CopilotBase):
    type: Literal["screen_context"] = "screen_context"
    session_id: str
    extracted_text: str
    application_name: str | None = None
    window_title: str | None = None


class WSPing(CopilotBase):
    type: Literal["ping"] = "ping"


class WSError(CopilotBase):
    event: Literal["error"] = "error"
    code: str
    message: str
    recoverable: bool = True


# ── Health ────────────────────────────────────────────────────────────────────

class HealthResponse(CopilotBase):
    status: Literal["ok", "degraded", "unhealthy"]
    service: str
    version: str
    checks: dict[str, bool]
    uptime_seconds: float


# ── Generic paginated response ────────────────────────────────────────────────

class PaginatedResponse(CopilotBase):
    items: list[Any]
    total: int
    page: int
    page_size: int
    has_more: bool
