"""add_title_to_meeting_sessions

Revision ID: 002_add_title_to_meeting_sessions
Revises: 001_initial
Create Date: 2026-05-21 00:00:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "002_add_title_to_meeting_sessions"
down_revision = "001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "meeting_sessions",
        sa.Column("title", sa.String(length=200), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("meeting_sessions", "title")
