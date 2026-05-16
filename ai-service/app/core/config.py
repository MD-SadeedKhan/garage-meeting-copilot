"""
Garage Meeting Copilot — Application Configuration
Pydantic Settings with environment-based configuration.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import AnyHttpUrl, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Service Identity ──────────────────────
    service_name: str = "garage-meeting-copilot"
    environment: Literal["development", "staging", "production"] = "production"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    secret_key: str = Field(..., min_length=32)

    # ── Garage Ecosystem Integration ──────────
    garage_api_base_url: AnyHttpUrl = Field(...)
    garage_jwt_secret: str = Field(..., min_length=16)
    garage_jwt_algorithm: str = "HS256"
    garage_jwt_audience: str = "garage-platform"

    # ── Server ────────────────────────────────
    ai_service_host: str = "0.0.0.0"
    ai_service_port: int = 8000
    realtime_gateway_port: int = 8001

    # ── CORS ──────────────────────────────────
    allowed_origins: str = "http://localhost:1420"

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def parse_origins(cls, v: str | list[str]) -> str:
        if isinstance(v, list):
            return ",".join(v)
        return v

    # ── OpenAI ────────────────────────────────
    openai_api_key: str = Field(...)
    openai_llm_model: str = "gpt-4.1"
    openai_embedding_model: str = "text-embedding-3-large"
    openai_max_tokens: int = 4096

    # ── Deepgram ──────────────────────────────
    deepgram_api_key: str = Field(...)
    deepgram_model: str = "nova-3"
    deepgram_language: str = "en-US"
    deepgram_punctuate: bool = True
    deepgram_diarize: bool = True
    deepgram_smart_format: bool = True

    # ── PostgreSQL ────────────────────────────
    database_url: str = Field(...)
    postgres_pool_size: int = 20
    postgres_max_overflow: int = 10
    postgres_pool_timeout: int = 30

    # ── Redis ─────────────────────────────────
    redis_url: str = Field(...)
    redis_max_connections: int = 100

    # ── Qdrant ────────────────────────────────
    qdrant_host: str = "qdrant"
    qdrant_port: int = 6333
    qdrant_collection_transcripts: str = "meeting_transcripts"
    qdrant_collection_summaries: str = "meeting_summaries"
    qdrant_vector_size: int = 3072

    # ── AWS S3 ────────────────────────────────
    aws_access_key_id: str = Field(...)
    aws_secret_access_key: str = Field(...)
    aws_region: str = "us-east-1"
    s3_bucket_artifacts: str = "garage-copilot-artifacts"
    s3_bucket_recordings: str = "garage-copilot-recordings"

    # ── AI Pipeline Config ────────────────────
    suggestion_interval_seconds: int = 4
    summary_interval_seconds: int = 60
    action_item_interval_seconds: int = 30
    max_transcript_context_tokens: int = 8000
    max_meeting_memory_chunks: int = 50

    # ── Rate Limiting ─────────────────────────
    rate_limit_per_minute: int = 120
    rate_limit_ws_connections_per_user: int = 100


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
