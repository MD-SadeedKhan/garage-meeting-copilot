"""Initial schema — Garage Meeting Copilot

Revision ID: 001_initial
Revises:
Create Date: 2025-01-01 00:00:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── meeting_sessions ──────────────────────
    op.create_table(
        "meeting_sessions",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("garage_meeting_id", sa.String(255), nullable=False),
        sa.Column("user_id", sa.String(255), nullable=False),
        sa.Column("organization_id", sa.String(255), nullable=False),
        sa.Column("workspace_id", sa.String(255), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="active"),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata", JSONB, nullable=False, server_default="{}"),
    )
    op.create_index("ix_meeting_sessions_garage_meeting_id", "meeting_sessions", ["garage_meeting_id"])
    op.create_index("ix_meeting_sessions_user_id", "meeting_sessions", ["user_id"])
    op.create_index("ix_meeting_sessions_workspace_id", "meeting_sessions", ["workspace_id"])
    op.create_index("ix_meeting_sessions_status", "meeting_sessions", ["status"])

    # ── transcript_chunks ─────────────────────
    op.create_table(
        "transcript_chunks",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "session_id",
            UUID(as_uuid=False),
            sa.ForeignKey("meeting_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sequence_number", sa.Integer, nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("speaker_label", sa.String(100), nullable=True),
        sa.Column("start_time", sa.Float, nullable=False, server_default="0"),
        sa.Column("end_time", sa.Float, nullable=False, server_default="0"),
        sa.Column("confidence", sa.Float, nullable=False, server_default="0"),
        sa.Column("is_final", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("qdrant_point_id", sa.String(255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index("ix_transcript_chunks_session_id", "transcript_chunks", ["session_id"])
    op.create_index("ix_transcript_chunks_speaker", "transcript_chunks", ["speaker_label"])
    op.create_index("ix_transcript_chunks_is_final", "transcript_chunks", ["is_final"])

    # ── meeting_summaries ─────────────────────
    op.create_table(
        "meeting_summaries",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "session_id",
            UUID(as_uuid=False),
            sa.ForeignKey("meeting_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("summary_type", sa.String(50), nullable=False, server_default="rolling"),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("transcript_range_start", sa.Integer, nullable=False, server_default="0"),
        sa.Column("transcript_range_end", sa.Integer, nullable=False, server_default="0"),
        sa.Column("token_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("s3_key", sa.String(512), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index("ix_meeting_summaries_session_id", "meeting_summaries", ["session_id"])
    op.create_index("ix_meeting_summaries_summary_type", "meeting_summaries", ["summary_type"])

    # ── action_items ──────────────────────────
    op.create_table(
        "action_items",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "session_id",
            UUID(as_uuid=False),
            sa.ForeignKey("meeting_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("assignee", sa.String(255), nullable=True),
        sa.Column("due_date", sa.String(100), nullable=True),
        sa.Column("priority", sa.String(20), nullable=False, server_default="medium"),
        sa.Column("status", sa.String(50), nullable=False, server_default="open"),
        sa.Column("source_transcript_chunk_id", sa.String(255), nullable=True),
        sa.Column("confidence_score", sa.Float, nullable=False, server_default="0.9"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index("ix_action_items_session_id", "action_items", ["session_id"])
    op.create_index("ix_action_items_status", "action_items", ["status"])
    op.create_index("ix_action_items_assignee", "action_items", ["assignee"])

    # ── ai_interactions ────────────────────────
    op.create_table(
        "ai_interactions",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "session_id",
            UUID(as_uuid=False),
            sa.ForeignKey("meeting_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("interaction_type", sa.String(50), nullable=False, server_default="chat"),
        sa.Column("user_message", sa.Text, nullable=True),
        sa.Column("ai_response", sa.Text, nullable=False),
        sa.Column("context_chunks_used", JSONB, nullable=False, server_default="[]"),
        sa.Column("prompt_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index("ix_ai_interactions_session_id", "ai_interactions", ["session_id"])
    op.create_index("ix_ai_interactions_interaction_type", "ai_interactions", ["interaction_type"])

    # ── screen_contexts ────────────────────────
    op.create_table(
        "screen_contexts",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("session_id", sa.String(255), nullable=False),
        sa.Column("extracted_text", sa.Text, nullable=False),
        sa.Column("application_name", sa.String(255), nullable=True),
        sa.Column("window_title", sa.String(500), nullable=True),
        sa.Column("s3_screenshot_key", sa.String(512), nullable=True),
        sa.Column(
            "captured_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index("ix_screen_contexts_session_id", "screen_contexts", ["session_id"])


def downgrade() -> None:
    op.drop_table("screen_contexts")
    op.drop_table("ai_interactions")
    op.drop_table("action_items")
    op.drop_table("meeting_summaries")
    op.drop_table("transcript_chunks")
    op.drop_table("meeting_sessions")
