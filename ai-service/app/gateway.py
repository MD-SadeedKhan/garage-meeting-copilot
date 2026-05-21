"""
Garage Meeting Copilot — Realtime WebSocket Gateway
Core streaming engine for audio, transcripts, and AI events.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import time
import uuid
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import (
    FastAPI,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal, check_db_connection
from app.core.logging import configure_logging, get_logger
from app.core.redis import RedisStreamState, check_redis_connection, get_redis
from app.middleware.garage_auth import GarageAuthContext, extract_ws_token
from app.schemas.copilot import HealthResponse
from app.services.ai.langgraph_pipeline import (
    MeetingContextPipeline,
    SuggestionPipeline,
    SummaryPipeline,
)
from app.services.memory.qdrant_retriever import qdrant_retriever
from app.services.ocr.screen_ocr import screen_ocr_pipeline
from app.services.transcription.deepgram_service import (
    DeepgramStreamingService,
    deepgram_manager,
)

configure_logging()
logger = get_logger(__name__)
settings = get_settings()

# ── App Setup ─────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Garage Meeting Copilot — Realtime Gateway",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.allowed_origins.split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_start_time = time.monotonic()

# Module-level pipeline instances
_context_pipeline: MeetingContextPipeline | None = None
_suggestion_pipeline = SuggestionPipeline()
_summary_pipeline = SummaryPipeline()


def get_context_pipeline() -> MeetingContextPipeline:
    global _context_pipeline
    if _context_pipeline is None:
        _context_pipeline = MeetingContextPipeline(qdrant_retriever)
    return _context_pipeline


# ── Connection Manager ────────────────────────────────────────────────────────

class ConnectionManager:
    """
    Manages active WebSocket connections per session.
    Handles broadcast and targeted messaging.
    """

    def __init__(self) -> None:
        # session_id -> list of connected WebSockets
        self._connections: dict[str, list[WebSocket]] = {}
        # ws -> session_id
        self._ws_to_session: dict[WebSocket, str] = {}
        # session_id -> set of user_ids
        self._session_users: dict[str, set[str]] = {}

    async def connect(
        self,
        websocket: WebSocket,
        session_id: str,
        user_id: str,
    ) -> None:
        await websocket.accept()
        if session_id not in self._connections:
            self._connections[session_id] = []
            self._session_users[session_id] = set()

        self._connections[session_id].append(websocket)
        self._ws_to_session[websocket] = session_id
        self._session_users[session_id].add(user_id)

        logger.info(
            "ws_connected",
            session_id=session_id,
            user_id=user_id,
            total_connections=len(self._connections[session_id]),
        )

    def disconnect(self, websocket: WebSocket) -> str | None:
        session_id = self._ws_to_session.pop(websocket, None)
        if session_id and session_id in self._connections:
            try:
                self._connections[session_id].remove(websocket)
            except ValueError:
                pass
            if not self._connections[session_id]:
                del self._connections[session_id]
                self._session_users.pop(session_id, None)
        return session_id

    async def send_to_session(
        self,
        session_id: str,
        payload: dict[str, Any],
    ) -> None:
        """Broadcast a message to all WebSockets in a session."""
        connections = self._connections.get(session_id, [])
        disconnected = []

        for ws in connections:
            try:
                await ws.send_json(payload)
            except Exception:
                disconnected.append(ws)

        for ws in disconnected:
            self.disconnect(ws)

    async def send_to_websocket(
        self,
        websocket: WebSocket,
        payload: dict[str, Any],
    ) -> None:
        """Send a message to a specific WebSocket."""
        try:
            await websocket.send_json(payload)
        except Exception as e:
            logger.warning("ws_send_failed", error=str(e))

    def connection_count(self, session_id: str) -> int:
        return len(self._connections.get(session_id, []))


manager = ConnectionManager()


# ── Transcript helpers ────────────────────────────────────────────────────────

def _latest_speaker_line(transcript: str) -> tuple[str | None, str | None]:
    """Return (speaker, text) of the most recent non-empty line in
    the transcript, or (None, None) if empty. Speaker is
    lower-cased; supports both `speaker: text` and `[speaker] text`
    formats."""
    for raw in reversed(transcript.splitlines()):
        s = raw.strip()
        if not s:
            continue
        if s.startswith("[") and "]" in s:
            head = s[1:s.index("]")].strip().lower()
            tail = s[s.index("]") + 1:].lstrip(": ").strip()
            return head, tail
        if ":" in s:
            head, _, tail = s.partition(":")
            return head.strip().lower(), tail.strip()
        return None, s
    return None, None


def _tx_hash(transcript: str) -> str:
    """Cheap content hash of the recent-transcript snapshot. Used as
    a per-loop dedupe key so we don't spend an LLM call when nothing
    new has been transcribed since last fire. Whitespace-normalised
    so trivial differences don't bust the hash."""
    normalized = "\n".join(line.strip() for line in transcript.splitlines() if line.strip())
    return hashlib.md5(normalized.encode("utf-8")).hexdigest()


def _line_hash(text: str) -> str:
    """Hash of a single utterance, used to detect 'same contact line
    we already responded to' independent of what the host added
    afterwards."""
    return hashlib.md5(text.strip().lower().encode("utf-8")).hexdigest()


# ── Background AI Tasks ───────────────────────────────────────────────────────

class SessionAIOrchestrator:
    """
    Per-session AI orchestrator that runs background tasks:
    - Periodic suggestion generation
    - Rolling summary updates
    - Action item extraction
    Triggered by transcript accumulation via Redis.
    """

    def __init__(
        self,
        session_id: str,
        garage_meeting_id: str,
        organization_id: str,
        redis_state: RedisStreamState,
    ) -> None:
        self._session_id = session_id
        self._garage_meeting_id = garage_meeting_id
        self._organization_id = organization_id
        self._redis = redis_state
        self._running = False
        self._tasks: list[asyncio.Task[None]] = []
        self._last_summary_chunk_count = 0
        self._last_action_item_chunk_count = 0
        # Suggestion loop dedupes on the *last contact utterance* —
        # adding host filler after a contact line shouldn't re-fire,
        # but a NEW contact utterance should.
        self._last_suggestion_contact_hash: str | None = None
        # Summary + action-items dedupe on the whole transcript
        # snapshot — they aren't "react to the latest line" loops,
        # they just shouldn't re-spin the LLM on unchanged content.
        self._last_summary_tx_hash: str | None = None
        self._last_action_items_tx_hash: str | None = None

    async def start(self) -> None:
        self._running = True
        self._tasks = [
            asyncio.create_task(redis_transcript_broadcaster(self._session_id)),
            asyncio.create_task(self._suggestion_loop()),
            asyncio.create_task(self._summary_loop()),
            asyncio.create_task(self._action_item_loop()),
        ]
        logger.info("session_orchestrator_started", session_id=self._session_id)

    async def stop(self) -> None:
        self._running = False
        for task in self._tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        logger.info("session_orchestrator_stopped", session_id=self._session_id)

    async def _suggestion_loop(self) -> None:
        """Generate AI suggestions every N seconds from recent transcript."""
        while self._running:
            try:
                await asyncio.sleep(settings.suggestion_interval_seconds)
                transcript = await self._redis.get_recent_transcript_text(
                    self._session_id, last_n=30
                )
                if not transcript.strip():
                    continue

                # Only fire when the LATEST line is from the contact.
                # That captures the intent "react to what the other
                # person just said". If the most recent speaker is the
                # host, they're already mid-thought — let them finish.
                last_speaker, last_text = _latest_speaker_line(transcript)
                logger.info(
                    "suggestion_loop_tick",
                    session_id=self._session_id,
                    last_speaker=last_speaker,
                    last_text_snippet=(last_text or "")[:80],
                    transcript_chars=len(transcript),
                )
                if last_speaker != "contact" or not last_text:
                    continue

                # Dedupe on the contact utterance itself so we don't
                # re-fire while the host is silent (transcript-wide
                # hash would change on every host filler word and
                # bust the dedupe).
                contact_hash = _line_hash(last_text)
                if contact_hash == self._last_suggestion_contact_hash:
                    logger.info(
                        "suggestion_loop_skip_dedupe",
                        session_id=self._session_id,
                    )
                    continue
                self._last_suggestion_contact_hash = contact_hash

                screen_ctx = ""
                cached_screen = await self._redis.get_cached_suggestion(
                    f"screen:{self._session_id}"
                )
                if cached_screen:
                    screen_ctx = cached_screen.get("text", "")

                # Pull the everything-so-far rolling summary + the
                # meeting metadata so the suggestion pipeline sees the
                # FULL arc of the call, not just the last 30 lines.
                rolling_summary = ""
                cached_summary = await self._redis.get_cached_suggestion(
                    f"summary:{self._session_id}"
                )
                if cached_summary:
                    rolling_summary = cached_summary.get("content", "")

                meeting_context = await self._redis.get_cached_suggestion(
                    f"meeting_ctx:{self._session_id}"
                ) or {}

                suggestions = await _suggestion_pipeline.generate(
                    session_id=self._session_id,
                    recent_transcript=transcript,
                    screen_context=screen_ctx,
                    rolling_summary=rolling_summary,
                    meeting_context=meeting_context,
                )

                if suggestions:
                    event = {
                        "event": "suggestions",
                        "session_id": self._session_id,
                        "suggestions": suggestions,
                        "generated_at": time.time(),
                    }
                    await manager.send_to_session(self._session_id, event)
                    await self._redis.publish(
                        self._session_id, "suggestions", event
                    )

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(
                    "suggestion_loop_error",
                    session_id=self._session_id,
                    error=str(e),
                )

    async def _summary_loop(self) -> None:
        """Generate rolling summary every N seconds."""
        while self._running:
            try:
                await asyncio.sleep(settings.summary_interval_seconds)
                transcript = await self._redis.get_recent_transcript_text(
                    self._session_id, last_n=100
                )
                if not transcript.strip():
                    continue

                # Dedupe — don't regenerate the summary if the
                # transcript hasn't changed since last run.
                tx_hash = _tx_hash(transcript)
                if tx_hash == self._last_summary_tx_hash:
                    continue
                self._last_summary_tx_hash = tx_hash

                # Get previous summary from Redis cache
                prev_data = await self._redis.get_cached_suggestion(
                    f"summary:{self._session_id}"
                )
                prev_summary = prev_data.get("content", "") if prev_data else ""

                new_summary = await _summary_pipeline.generate_rolling_summary(
                    session_id=self._session_id,
                    full_transcript=transcript,
                    previous_summary=prev_summary,
                )

                if new_summary:
                    # Cache summary
                    await self._redis.cache_suggestion(
                        f"summary:{self._session_id}",
                        {"content": new_summary},
                        ttl=3600,
                    )

                    event = {
                        "event": "summary",
                        "session_id": self._session_id,
                        "content": new_summary,
                        "summary_type": "rolling",
                        "generated_at": time.time(),
                    }
                    await manager.send_to_session(self._session_id, event)

                    # Persist to DB asynchronously
                    asyncio.create_task(
                        self._persist_summary(new_summary)
                    )

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(
                    "summary_loop_error",
                    session_id=self._session_id,
                    error=str(e),
                )

    async def _action_item_loop(self) -> None:
        """Extract action items every N seconds."""
        while self._running:
            try:
                await asyncio.sleep(settings.action_item_interval_seconds)
                transcript = await self._redis.get_recent_transcript_text(
                    self._session_id, last_n=50
                )
                if not transcript.strip():
                    continue

                # Action items only make sense after at least one
                # back-and-forth — skip pure monologue.
                has_contact = any(
                    line.strip().lower().startswith(("contact:", "[contact]"))
                    for line in transcript.splitlines()
                )
                if not has_contact:
                    continue

                # Dedupe — skip if transcript snapshot is unchanged.
                tx_hash = _tx_hash(transcript)
                if tx_hash == self._last_action_items_tx_hash:
                    continue
                self._last_action_items_tx_hash = tx_hash

                items = await _summary_pipeline.extract_action_items(
                    session_id=self._session_id,
                    transcript=transcript,
                )

                if items:
                    event = {
                        "event": "action_items",
                        "session_id": self._session_id,
                        "items": items,
                        "generated_at": time.time(),
                    }
                    await manager.send_to_session(self._session_id, event)

                    # Persist to DB
                    asyncio.create_task(
                        self._persist_action_items(items)
                    )

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(
                    "action_item_loop_error",
                    session_id=self._session_id,
                    error=str(e),
                )

    async def _persist_summary(self, content: str) -> None:
        """Persist summary to PostgreSQL."""
        from app.repositories.copilot_repo import SummaryRepository
        try:
            async with AsyncSessionLocal() as db:
                repo = SummaryRepository(db)
                await repo.create(
                    session_id=self._session_id,
                    content=content,
                    summary_type="rolling",
                )
                await db.commit()
        except Exception as e:
            logger.error("summary_persist_failed", error=str(e))

    async def _persist_action_items(self, items: list[dict[str, Any]]) -> None:
        """Persist action items to PostgreSQL."""
        from app.repositories.copilot_repo import ActionItemRepository
        try:
            async with AsyncSessionLocal() as db:
                repo = ActionItemRepository(db)
                await repo.bulk_upsert(self._session_id, items)
                await db.commit()
        except Exception as e:
            logger.error("action_items_persist_failed", error=str(e))


# Track active orchestrators
_orchestrators: dict[str, SessionAIOrchestrator] = {}


# ── Redis Pub/Sub Listener ────────────────────────────────────────────────────

async def redis_transcript_broadcaster(session_id: str) -> None:
    """
    Subscribe to Redis transcript channel and broadcast to WebSocket clients.
    Runs as a background task per session.
    """
    redis_state = RedisStreamState(get_redis())
    try:
        async with redis_state.subscribe(session_id, "transcript") as pubsub:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    try:
                        payload = json.loads(message["data"])
                        await manager.send_to_session(session_id, payload)
                    except Exception as e:
                        logger.warning("broadcaster_parse_error", error=str(e))
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.error("redis_broadcaster_error", session_id=session_id, error=str(e))


# ── WebSocket Handler ─────────────────────────────────────────────────────────

@app.websocket("/ws/copilot")
async def copilot_websocket(
    websocket: WebSocket,
    token: str = Query(..., description="Garage JWT"),
    session_id: str = Query(..., description="Copilot session ID"),
):
    """
    Primary WebSocket endpoint for the Garage Meeting Copilot.

    Client sends:
      {"type": "audio", "data": "<base64 PCM>", "sequence": N, "source": "microphone"}
      {"type": "chat", "message": "..."}
      {"type": "screen_context", "extracted_text": "...", "application_name": "..."}
      {"type": "ping"}

    Server sends:
      {"event": "transcript", ...}
      {"event": "suggestions", ...}
      {"event": "summary", ...}
      {"event": "action_items", ...}
      {"event": "chat_token", ...}
      {"event": "chat_complete", ...}
      {"event": "error", ...}
    """
    # Validate JWT for this WebSocket connection
    try:
        auth_context = await extract_ws_token(token)
    except HTTPException:
        await websocket.close(code=4401, reason="Unauthorized")
        return

    redis = get_redis()
    redis_state = RedisStreamState(redis)

    # Rate limit: max N concurrent WS connections per user
    allowed, _count = await redis_state.check_rate_limit(
        f"ws:{auth_context.user_id}",
        limit=settings.rate_limit_ws_connections_per_user,
        window_seconds=300,
    )
    if not allowed:
        await websocket.close(code=4029, reason="Too many connections")
        return

    # Validate session exists in Redis
    session_data = await redis_state.get_session(session_id)
    if not session_data:
        await websocket.close(code=4004, reason="Session not found")
        return

    # Connect WebSocket
    await manager.connect(websocket, session_id, auth_context.user_id)

    garage_meeting_id = session_data.get("meeting_id", "")
    organization_id = auth_context.organization_id

    # Start Deepgram streaming for this session (idempotent)
    transcript_tasks: list[asyncio.Task[None]] = []

    async def on_transcript_chunk(chunk: Any) -> None:
        """Called when Deepgram returns a transcript chunk."""
        # Index in Qdrant if final
        if chunk.is_final:
            asyncio.create_task(
                _index_transcript_chunk(
                    chunk,
                    garage_meeting_id,
                    auth_context.user_id,
                    organization_id,
                )
            )
            asyncio.create_task(
                _persist_transcript_chunk(chunk, session_id)
            )

    # Open one Deepgram stream per audio source (host mic vs the
    # remote-track mix). Each gets a forced speaker label so the
    # LLM sees `[host] ...` and `[contact] ...` lines instead of
    # Deepgram's anonymous "Speaker N".
    dg_self = await deepgram_manager.create_session(
        session_id=session_id,
        redis_state=redis_state,
        on_transcript=on_transcript_chunk,
        source="self",
    )
    dg_others = await deepgram_manager.create_session(
        session_id=session_id,
        redis_state=redis_state,
        on_transcript=on_transcript_chunk,
        source="others",
    )
    # Legacy "mixed" fallback for any client that hasn't been
    # updated to the dual-stream protocol — routes to a single
    # diarized stream with no forced label.
    dg_mixed = await deepgram_manager.create_session(
        session_id=session_id,
        redis_state=redis_state,
        on_transcript=on_transcript_chunk,
        source="mixed",
    )
    dg_by_source = {"self": dg_self, "others": dg_others, "mixed": dg_mixed}

    # Start per-session AI orchestrator (idempotent)
    if session_id not in _orchestrators:
        orchestrator = SessionAIOrchestrator(
            session_id=session_id,
            garage_meeting_id=garage_meeting_id,
            organization_id=organization_id,
            redis_state=redis_state,
        )
        await orchestrator.start()
        _orchestrators[session_id] = orchestrator

    # Send connected acknowledgement
    await websocket.send_json(
        {
            "event": "connected",
            "session_id": session_id,
            "user_id": auth_context.user_id,
        }
    )

    logger.info(
        "ws_session_ready",
        session_id=session_id,
        user_id=auth_context.user_id,
    )

    try:
        while True:
            raw = await websocket.receive_text()
            message = json.loads(raw)
            msg_type = message.get("type")

            if msg_type == "audio":
                # Decode and forward to the correct per-source
                # Deepgram stream so the resulting transcript carries
                # a known `host` / `contact` label.
                try:
                    audio_bytes = base64.b64decode(message["data"])
                    sequence = message.get("sequence", 0)
                    source = message.get("source", "mixed")
                    if source not in dg_by_source:
                        source = "mixed"
                    if sequence % 50 == 0:  # Log every 50 chunks
                        logger.info(
                            "📦 Received audio chunk #%d (%d bytes) source=%s",
                            sequence,
                            len(audio_bytes),
                            source,
                        )
                    await dg_by_source[source].send_audio(audio_bytes)
                except Exception as e:
                    logger.warning("audio_decode_error", error=str(e))

            elif msg_type == "chat":
                # Handle AI chat request — stream response back
                user_message = message.get("message", "").strip()
                if user_message:
                    asyncio.create_task(
                        _handle_chat(
                            websocket=websocket,
                            session_id=session_id,
                            organization_id=organization_id,
                            user_message=user_message,
                            redis_state=redis_state,
                        )
                    )

            elif msg_type == "screen_context":
                # Cache screen OCR context for AI enrichment
                extracted_text = message.get("extracted_text", "")
                truncated = screen_ocr_pipeline.truncate_for_context(
                    extracted_text, max_tokens=400
                )
                await redis_state.cache_suggestion(
                    f"screen:{session_id}",
                    {
                        "text": truncated,
                        "application_name": message.get("application_name"),
                        "window_title": message.get("window_title"),
                    },
                    ttl=60,
                )
                logger.debug(
                    "screen_context_cached",
                    session_id=session_id,
                    word_count=len(extracted_text.split()),
                )

            elif msg_type == "ping":
                await websocket.send_json({"event": "pong"})

            else:
                logger.warning(
                    "ws_unknown_message_type",
                    msg_type=msg_type,
                    session_id=session_id,
                )

    except WebSocketDisconnect:
        logger.info("ws_disconnected", session_id=session_id)
    except json.JSONDecodeError:
        logger.warning("ws_invalid_json", session_id=session_id)
    except Exception as e:
        logger.error(
            "ws_handler_error",
            session_id=session_id,
            error=str(e),
            exc_info=True,
        )
    finally:
        manager.disconnect(websocket)
        # If no more connections for this session, stop orchestrator
        if manager.connection_count(session_id) == 0:
            orch = _orchestrators.pop(session_id, None)
            if orch:
                asyncio.create_task(orch.stop())
            await deepgram_manager.end_session(session_id)


async def _handle_chat(
    websocket: WebSocket,
    session_id: str,
    organization_id: str,
    user_message: str,
    redis_state: RedisStreamState,
) -> None:
    """Stream AI chat response token by token to the overlay."""
    start = time.monotonic()
    full_response = ""

    recent_transcript = await redis_state.get_recent_transcript_text(
        session_id, last_n=40
    )

    screen_data = await redis_state.get_cached_suggestion(
        f"screen:{session_id}"
    )
    screen_context = screen_data.get("text", "") if screen_data else ""

    pipeline = get_context_pipeline()

    try:
        async for token in pipeline.stream(
            session_id=session_id,
            organization_id=organization_id,
            user_query=user_message,
            recent_transcript=recent_transcript,
            screen_context=screen_context,
        ):
            if token:
                full_response += token
                await websocket.send_json(
                    {
                        "event": "chat_token",
                        "session_id": session_id,
                        "token": token,
                        "is_final": False,
                    }
                )

        latency_ms = int((time.monotonic() - start) * 1000)

        await websocket.send_json(
            {
                "event": "chat_complete",
                "session_id": session_id,
                "full_response": full_response,
                "latency_ms": latency_ms,
            }
        )

        # Persist interaction
        asyncio.create_task(
            _persist_ai_interaction(
                session_id=session_id,
                user_message=user_message,
                ai_response=full_response,
                latency_ms=latency_ms,
            )
        )

    except Exception as e:
        logger.error("chat_stream_error", session_id=session_id, error=str(e))
        await websocket.send_json(
            {
                "event": "error",
                "code": "CHAT_FAILED",
                "message": "AI response failed. Please try again.",
                "recoverable": True,
            }
        )


async def _index_transcript_chunk(
    chunk: Any,
    garage_meeting_id: str,
    user_id: str,
    organization_id: str,
) -> None:
    """Background: Index final transcript chunk in Qdrant."""
    try:
        await qdrant_retriever.index_transcript_chunk(
            session_id=chunk.session_id,
            chunk_id=chunk.chunk_id,
            text=chunk.text,
            speaker_label=chunk.speaker_label,
            start_time=chunk.start_time,
            end_time=chunk.end_time,
            is_final=chunk.is_final,
            sequence_number=chunk.sequence_number,
            garage_meeting_id=garage_meeting_id,
            user_id=user_id,
            organization_id=organization_id,
        )
    except Exception as e:
        logger.error("qdrant_indexing_failed", chunk_id=chunk.chunk_id, error=str(e))


async def _persist_transcript_chunk(chunk: Any, session_id: str) -> None:
    """Background: Persist transcript chunk to PostgreSQL."""
    from app.repositories.copilot_repo import TranscriptRepository
    try:
        async with AsyncSessionLocal() as db:
            repo = TranscriptRepository(db)
            await repo.create(
                session_id=session_id,
                sequence_number=chunk.sequence_number,
                text=chunk.text,
                speaker_label=chunk.speaker_label,
                start_time=chunk.start_time,
                end_time=chunk.end_time,
                confidence=chunk.confidence,
                is_final=chunk.is_final,
            )
            await db.commit()
    except Exception as e:
        logger.error("transcript_persist_failed", error=str(e))


async def _persist_ai_interaction(
    session_id: str,
    user_message: str,
    ai_response: str,
    latency_ms: int,
) -> None:
    """Background: Persist AI chat interaction to PostgreSQL."""
    from app.repositories.copilot_repo import (
        AIInteractionRepository,
        MeetingSessionRepository,
    )
    try:
        async with AsyncSessionLocal() as db:
            repo = AIInteractionRepository(db)
            await repo.create(
                session_id=session_id,
                interaction_type="chat",
                user_message=user_message,
                ai_response=ai_response,
                latency_ms=latency_ms,
            )
            # Cheap autoname: if the session has no title yet, use first 80 chars
            # of the first user message so the FE list isn't all "Untitled".
            if user_message:
                session_repo = MeetingSessionRepository(db)
                await session_repo.set_title_if_empty(
                    session_id, user_message.strip()[:80]
                )
            await db.commit()
    except Exception as e:
        logger.error("interaction_persist_failed", error=str(e))


# ── Health Endpoint ───────────────────────────────────────────────────────────

@app.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    db_ok = await check_db_connection()
    redis_ok = await check_redis_connection()
    qdrant_ok = await qdrant_retriever.check_connection()

    all_ok = db_ok and redis_ok and qdrant_ok
    return HealthResponse(
        status="ok" if all_ok else "degraded",
        service="realtime-gateway",
        version="1.0.0",
        checks={
            "database": db_ok,
            "redis": redis_ok,
            "qdrant": qdrant_ok,
        },
        uptime_seconds=time.monotonic() - _start_time,
    )


@app.on_event("startup")
async def startup() -> None:
    await qdrant_retriever.ensure_collections()
    logger.info("realtime_gateway_started")


@app.on_event("shutdown")
async def shutdown() -> None:
    await deepgram_manager.shutdown()
    for orch in _orchestrators.values():
        await orch.stop()
    logger.info("realtime_gateway_shutdown")
