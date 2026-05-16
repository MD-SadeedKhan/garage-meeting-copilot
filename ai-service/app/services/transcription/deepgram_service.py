"""
Garage Meeting Copilot — Deepgram Streaming Transcription Service
Realtime speech-to-text with speaker diarization via Deepgram.
"""
from __future__ import annotations

import asyncio
import base64
import json
import uuid
from collections.abc import AsyncGenerator
from typing import Any

import websockets
from deepgram import (
    DeepgramClient,
    DeepgramClientOptions,
    LiveOptions,
    LiveResultResponse,
    LiveTranscriptionEvents,
)

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.redis import RedisStreamState

logger = get_logger(__name__)


class TranscriptChunkResult:
    """Normalised result from Deepgram with metadata."""

    __slots__ = (
        "chunk_id",
        "session_id",
        "text",
        "speaker_label",
        "start_time",
        "end_time",
        "confidence",
        "is_final",
        "sequence_number",
        "words",
    )

    def __init__(
        self,
        session_id: str,
        text: str,
        speaker_label: str | None,
        start_time: float,
        end_time: float,
        confidence: float,
        is_final: bool,
        sequence_number: int,
        words: list[dict[str, Any]],
    ) -> None:
        self.chunk_id = str(uuid.uuid4())
        self.session_id = session_id
        self.text = text
        self.speaker_label = speaker_label
        self.start_time = start_time
        self.end_time = end_time
        self.confidence = confidence
        self.is_final = is_final
        self.sequence_number = sequence_number
        self.words = words

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "session_id": self.session_id,
            "text": self.text,
            "speaker_label": self.speaker_label,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "confidence": self.confidence,
            "is_final": self.is_final,
            "sequence_number": self.sequence_number,
        }


class DeepgramStreamingService:
    """
    Manages a live Deepgram WebSocket connection per meeting session.
    Receives audio bytes, returns TranscriptChunkResult via async queue.
    """

    def __init__(
        self,
        session_id: str,
        redis_state: RedisStreamState,
        on_transcript: Any,  # Callable[[TranscriptChunkResult], Awaitable[None]]
        *,
        source: str = "mixed",
        forced_speaker_label: str | None = None,
    ) -> None:
        self._session_id = session_id
        self._redis = redis_state
        self._on_transcript = on_transcript
        self._settings = get_settings()
        self._sequence = 0
        self._connection: Any = None
        self._audio_queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=512)
        self._running = False
        self._client: DeepgramClient | None = None
        # Used to label transcripts so the LLM can tell "what the
        # host said" vs "what the contact said". When set, we ignore
        # Deepgram's anonymous diarization output for this stream.
        self._source = source
        self._forced_speaker_label = forced_speaker_label

    async def start(self) -> None:
        """Initialise Deepgram client and open live connection."""
        self._client = DeepgramClient(
            self._settings.deepgram_api_key,
            config=DeepgramClientOptions(verbose=False),
        )

        options = LiveOptions(
            model=self._settings.deepgram_model,
            language=self._settings.deepgram_language,
            punctuate=self._settings.deepgram_punctuate,
            diarize=self._settings.deepgram_diarize,
            smart_format=self._settings.deepgram_smart_format,
            interim_results=True,
            utterance_end_ms="1000",
            vad_events=True,
            encoding="linear16",
            sample_rate=16000,
            channels=1,
        )

        self._connection = self._client.listen.asyncwebsocket.v("1")

        # Register event handlers
        self._connection.on(
            LiveTranscriptionEvents.Transcript,
            self._handle_transcript,
        )
        self._connection.on(
            LiveTranscriptionEvents.Error,
            self._handle_error,
        )
        self._connection.on(
            LiveTranscriptionEvents.Close,
            self._handle_close,
        )

        started = await self._connection.start(options)
        if not started:
            raise RuntimeError("Failed to start Deepgram live connection")

        self._running = True
        logger.info(
            "deepgram_connection_started",
            session_id=self._session_id,
        )

    async def send_audio(self, audio_bytes: bytes) -> None:
        """Queue audio bytes for sending to Deepgram."""
        if self._running and not self._audio_queue.full():
            await self._audio_queue.put(audio_bytes)

    async def run_send_loop(self) -> None:
        """
        Continuously drain the audio queue and send to Deepgram.
        Run as a background task alongside the WebSocket receiver.
        """
        while self._running:
            try:
                audio = await asyncio.wait_for(
                    self._audio_queue.get(),
                    timeout=1.0,
                )
                if audio is None:
                    break
                await self._connection.send(audio)
                self._audio_queue.task_done()
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(
                    "deepgram_send_error",
                    session_id=self._session_id,
                    error=str(e),
                )
                break

    async def _handle_transcript(
        self,
        _client: Any,
        result: LiveResultResponse,
        **kwargs: Any,
    ) -> None:
        """Process Deepgram transcript result."""
        try:
            channel = result.channel
            alternatives = channel.alternatives
            if not alternatives:
                return

            alt = alternatives[0]
            text = alt.transcript.strip()
            if not text:
                return

            is_final = result.is_final
            self._sequence += 1

            # If we know which side this stream came from (host mic
            # vs remote LiveKit tracks), label it explicitly. That
            # beats Deepgram's anonymous "Speaker N" diarization which
            # the LLM can't map back to a real identity.
            words = alt.words or []
            if self._forced_speaker_label:
                speaker_label: str | None = self._forced_speaker_label
            elif words and hasattr(words[0], "speaker"):
                speaker_num = words[0].speaker
                speaker_label = f"Speaker {speaker_num + 1}"
            else:
                speaker_label = None

            start_time = result.start or 0.0
            duration = result.duration or 0.0
            end_time = start_time + duration

            confidence = alt.confidence or 0.0

            chunk = TranscriptChunkResult(
                session_id=self._session_id,
                text=text,
                speaker_label=speaker_label,
                start_time=start_time,
                end_time=end_time,
                confidence=confidence,
                is_final=is_final,
                sequence_number=self._sequence,
                words=[
                    {
                        "word": w.word,
                        "start": w.start,
                        "end": w.end,
                        "confidence": w.confidence,
                        "speaker": getattr(w, "speaker", None),
                    }
                    for w in words
                ],
            )

            # Buffer in Redis only on FINAL results. Interim results
            # are partial guesses that mutate every ~200ms ("Hi" →
            # "Hi there" → "Hi there how are you?") — appending them
            # all bloats the transcript with near-duplicates and
            # breaks any "did the contact just say something new?"
            # dedupe downstream. The live WS broadcast below still
            # gets interims so the FE can render live captions.
            if is_final:
                await self._redis.append_transcript_chunk(
                    self._session_id,
                    chunk.to_dict(),
                )

            # Publish to session channel for WebSocket broadcast
            await self._redis.publish(
                self._session_id,
                "transcript",
                {
                    "event": "transcript",
                    **chunk.to_dict(),
                },
            )

            # Call registered callback
            if self._on_transcript:
                await self._on_transcript(chunk)

        except Exception as e:
            logger.error(
                "deepgram_transcript_handler_error",
                session_id=self._session_id,
                error=str(e),
                exc_info=True,
            )

    async def _handle_error(
        self,
        _client: Any,
        error: Any,
        **kwargs: Any,
    ) -> None:
        logger.error(
            "deepgram_connection_error",
            session_id=self._session_id,
            error=str(error),
        )

    async def _handle_close(
        self,
        _client: Any,
        close: Any,
        **kwargs: Any,
    ) -> None:
        logger.info(
            "deepgram_connection_closed",
            session_id=self._session_id,
        )
        self._running = False

    async def stop(self) -> None:
        """Gracefully close the Deepgram connection."""
        self._running = False
        await self._audio_queue.put(None)  # Signal send loop to exit
        if self._connection:
            await self._connection.finish()
        logger.info("deepgram_connection_stopped", session_id=self._session_id)


class DeepgramSessionManager:
    """
    Manages multiple concurrent Deepgram streaming sessions.
    One DeepgramStreamingService per active meeting session.
    """

    def __init__(self) -> None:
        # Keyed by (copilot_session_id, source) so the host mic and
        # the remote-mix get independent Deepgram streams. Backwards-
        # compatible: legacy callers without a source land in the
        # "mixed" bucket.
        self._sessions: dict[tuple[str, str], DeepgramStreamingService] = {}
        self._tasks: dict[tuple[str, str], asyncio.Task[None]] = {}

    @staticmethod
    def _label_for_source(source: str) -> str | None:
        if source == "self":
            return "host"
        if source == "others":
            return "contact"
        return None

    async def create_session(
        self,
        session_id: str,
        redis_state: RedisStreamState,
        on_transcript: Any,
        *,
        source: str = "mixed",
    ) -> DeepgramStreamingService:
        key = (session_id, source)
        if key in self._sessions:
            return self._sessions[key]

        service = DeepgramStreamingService(
            session_id=session_id,
            redis_state=redis_state,
            on_transcript=on_transcript,
            source=source,
            forced_speaker_label=self._label_for_source(source),
        )
        await service.start()

        # Run the send loop as a background task
        task = asyncio.create_task(service.run_send_loop())
        self._tasks[key] = task
        self._sessions[key] = service

        logger.info(
            "deepgram_session_created",
            session_id=session_id,
            source=source,
        )
        return service

    async def get_session(
        self,
        session_id: str,
        source: str = "mixed",
    ) -> DeepgramStreamingService | None:
        return self._sessions.get((session_id, source))

    async def end_session(self, session_id: str) -> None:
        """End every Deepgram stream attached to this copilot session,
        regardless of source."""
        keys = [k for k in self._sessions if k[0] == session_id]
        for key in keys:
            service = self._sessions.pop(key, None)
            if service:
                await service.stop()

            task = self._tasks.pop(key, None)
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

            logger.info(
                "deepgram_session_ended",
                session_id=session_id,
                source=key[1],
            )

    async def shutdown(self) -> None:
        """Gracefully terminate all active sessions."""
        # Snapshot then end-by-session_id (which clears every source).
        for sid in {k[0] for k in list(self._sessions.keys())}:
            await self.end_session(sid)


# Module-level singleton
deepgram_manager = DeepgramSessionManager()
