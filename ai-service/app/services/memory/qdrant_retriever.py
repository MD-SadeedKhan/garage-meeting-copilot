"""
Garage Meeting Copilot — Qdrant Vector Retrieval Layer
Semantic embedding storage and retrieval for meeting memory.
"""
from __future__ import annotations

import uuid
from typing import Any

from openai import AsyncOpenAI
from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models as qdrant_models
from qdrant_client.http.exceptions import UnexpectedResponse

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class QdrantRetriever:
    """
    Manages Qdrant collections and provides semantic retrieval
    for transcript chunks, summaries, and meeting memory.
    """

    def __init__(self) -> None:
        self._settings = get_settings()
        self._client: AsyncQdrantClient | None = None
        self._openai: AsyncOpenAI | None = None

    async def _get_client(self) -> AsyncQdrantClient:
        if self._client is None:
            self._client = AsyncQdrantClient(
                host=self._settings.qdrant_host,
                port=self._settings.qdrant_port,
                timeout=30,
            )
        return self._client

    def _get_openai(self) -> AsyncOpenAI:
        if self._openai is None:
            self._openai = AsyncOpenAI(api_key=self._settings.openai_api_key)
        return self._openai

    # ── Collection Management ─────────────────

    async def ensure_collections(self) -> None:
        """Create Qdrant collections if they don't exist."""
        client = await self._get_client()
        vector_size = self._settings.qdrant_vector_size

        for collection_name in [
            self._settings.qdrant_collection_transcripts,
            self._settings.qdrant_collection_summaries,
        ]:
            try:
                await client.get_collection(collection_name)
                logger.debug("qdrant_collection_exists", name=collection_name)
            except (UnexpectedResponse, Exception):
                await client.create_collection(
                    collection_name=collection_name,
                    vectors_config=qdrant_models.VectorParams(
                        size=vector_size,
                        distance=qdrant_models.Distance.COSINE,
                        on_disk=True,
                    ),
                    optimizers_config=qdrant_models.OptimizersConfigDiff(
                        indexing_threshold=20000,
                        memmap_threshold=50000,
                    ),
                    hnsw_config=qdrant_models.HnswConfigDiff(
                        m=16,
                        ef_construct=100,
                        full_scan_threshold=10000,
                    ),
                )
                logger.info("qdrant_collection_created", name=collection_name)

    # ── Embedding Generation ──────────────────

    async def embed_text(self, text: str) -> list[float]:
        """Generate OpenAI text-embedding-3-large embedding."""
        openai = self._get_openai()
        response = await openai.embeddings.create(
            model=self._settings.openai_embedding_model,
            input=text.strip(),
        )
        return response.data[0].embedding

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Batch embed multiple texts."""
        openai = self._get_openai()
        response = await openai.embeddings.create(
            model=self._settings.openai_embedding_model,
            input=[t.strip() for t in texts],
        )
        return [item.embedding for item in response.data]

    # ── Transcript Indexing ───────────────────

    async def index_transcript_chunk(
        self,
        session_id: str,
        chunk_id: str,
        text: str,
        speaker_label: str | None,
        start_time: float,
        end_time: float,
        is_final: bool,
        sequence_number: int,
        garage_meeting_id: str,
        user_id: str,
        organization_id: str,
    ) -> str:
        """Index a transcript chunk into Qdrant for semantic retrieval."""
        if not text.strip():
            return chunk_id

        embedding = await self.embed_text(text)
        point_id = str(uuid.uuid4())

        client = await self._get_client()
        await client.upsert(
            collection_name=self._settings.qdrant_collection_transcripts,
            points=[
                qdrant_models.PointStruct(
                    id=point_id,
                    vector=embedding,
                    payload={
                        "chunk_id": chunk_id,
                        "session_id": session_id,
                        "garage_meeting_id": garage_meeting_id,
                        "user_id": user_id,
                        "organization_id": organization_id,
                        "text": text,
                        "speaker_label": speaker_label,
                        "start_time": start_time,
                        "end_time": end_time,
                        "is_final": is_final,
                        "sequence_number": sequence_number,
                    },
                )
            ],
        )

        logger.debug(
            "qdrant_transcript_indexed",
            chunk_id=chunk_id,
            session_id=session_id,
        )
        return point_id

    async def index_summary(
        self,
        session_id: str,
        summary_id: str,
        content: str,
        summary_type: str,
        garage_meeting_id: str,
        organization_id: str,
    ) -> str:
        """Index a meeting summary."""
        embedding = await self.embed_text(content)
        point_id = str(uuid.uuid4())

        client = await self._get_client()
        await client.upsert(
            collection_name=self._settings.qdrant_collection_summaries,
            points=[
                qdrant_models.PointStruct(
                    id=point_id,
                    vector=embedding,
                    payload={
                        "summary_id": summary_id,
                        "session_id": session_id,
                        "garage_meeting_id": garage_meeting_id,
                        "organization_id": organization_id,
                        "content": content,
                        "summary_type": summary_type,
                    },
                )
            ],
        )
        return point_id

    # ── Semantic Retrieval ────────────────────

    async def search_transcript(
        self,
        query: str,
        session_id: str,
        limit: int = 10,
        score_threshold: float = 0.65,
    ) -> list[dict[str, Any]]:
        """
        Semantic search over transcript chunks for a specific session.
        Returns ranked chunks most relevant to the query.
        """
        embedding = await self.embed_text(query)
        client = await self._get_client()

        results = await client.search(
            collection_name=self._settings.qdrant_collection_transcripts,
            query_vector=embedding,
            query_filter=qdrant_models.Filter(
                must=[
                    qdrant_models.FieldCondition(
                        key="session_id",
                        match=qdrant_models.MatchValue(value=session_id),
                    ),
                    qdrant_models.FieldCondition(
                        key="is_final",
                        match=qdrant_models.MatchValue(value=True),
                    ),
                ]
            ),
            limit=limit,
            score_threshold=score_threshold,
            with_payload=True,
        )

        return [
            {
                "score": hit.score,
                "text": hit.payload.get("text", ""),
                "speaker_label": hit.payload.get("speaker_label"),
                "start_time": hit.payload.get("start_time", 0.0),
                "chunk_id": hit.payload.get("chunk_id", ""),
                "sequence_number": hit.payload.get("sequence_number", 0),
            }
            for hit in results
        ]

    async def search_cross_meeting(
        self,
        query: str,
        organization_id: str,
        exclude_session_id: str | None = None,
        limit: int = 5,
        score_threshold: float = 0.70,
    ) -> list[dict[str, Any]]:
        """
        Search across all meetings for an organization — historical context.
        """
        embedding = await self.embed_text(query)
        client = await self._get_client()

        must_conditions: list[Any] = [
            qdrant_models.FieldCondition(
                key="organization_id",
                match=qdrant_models.MatchValue(value=organization_id),
            ),
        ]

        must_not_conditions: list[Any] = []
        if exclude_session_id:
            must_not_conditions.append(
                qdrant_models.FieldCondition(
                    key="session_id",
                    match=qdrant_models.MatchValue(value=exclude_session_id),
                )
            )

        results = await client.search(
            collection_name=self._settings.qdrant_collection_transcripts,
            query_vector=embedding,
            query_filter=qdrant_models.Filter(
                must=must_conditions,
                must_not=must_not_conditions if must_not_conditions else None,
            ),
            limit=limit,
            score_threshold=score_threshold,
            with_payload=True,
        )

        return [
            {
                "score": hit.score,
                "text": hit.payload.get("text", ""),
                "session_id": hit.payload.get("session_id", ""),
                "garage_meeting_id": hit.payload.get("garage_meeting_id", ""),
                "speaker_label": hit.payload.get("speaker_label"),
            }
            for hit in results
        ]

    async def get_meeting_context_chunks(
        self,
        query: str,
        session_id: str,
        organization_id: str,
        n_current: int = 8,
        n_historical: int = 3,
    ) -> dict[str, list[dict[str, Any]]]:
        """
        Retrieve combined current + historical context for RAG.
        """
        import asyncio

        current_task = asyncio.create_task(
            self.search_transcript(query, session_id, limit=n_current)
        )
        historical_task = asyncio.create_task(
            self.search_cross_meeting(
                query,
                organization_id,
                exclude_session_id=session_id,
                limit=n_historical,
            )
        )

        current, historical = await asyncio.gather(current_task, historical_task)
        return {"current": current, "historical": historical}

    async def delete_session_vectors(self, session_id: str) -> None:
        """Remove all vectors for a session (e.g., on data deletion request)."""
        client = await self._get_client()
        for collection in [
            self._settings.qdrant_collection_transcripts,
            self._settings.qdrant_collection_summaries,
        ]:
            await client.delete(
                collection_name=collection,
                points_selector=qdrant_models.FilterSelector(
                    filter=qdrant_models.Filter(
                        must=[
                            qdrant_models.FieldCondition(
                                key="session_id",
                                match=qdrant_models.MatchValue(value=session_id),
                            )
                        ]
                    )
                ),
            )
        logger.info("qdrant_session_vectors_deleted", session_id=session_id)

    async def check_connection(self) -> bool:
        try:
            client = await self._get_client()
            await client.get_collections()
            return True
        except Exception as e:
            logger.error("qdrant_health_check_failed", error=str(e))
            return False


# Module-level singleton
qdrant_retriever = QdrantRetriever()
