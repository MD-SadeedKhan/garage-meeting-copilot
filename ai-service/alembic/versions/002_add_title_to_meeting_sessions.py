"""add_title_to_meeting_sessions

Revision ID: 002_session_title
Revises: 001_initial
Create Date: 2026-05-21 00:00:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "002_session_title"
down_revision = "001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Idempotent — previous deploy may have ALTER'd the table successfully
    # before crashing on the alembic_version bookkeeping update (revision id
    # was >32 chars). Re-running this upgrade against a DB that already has
    # the column would otherwise blow up with "column already exists".
    bind = op.get_bind()
    existing = bind.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name='meeting_sessions' AND column_name='title'"
        )
    ).scalar()
    if not existing:
        op.add_column(
            "meeting_sessions",
            sa.Column("title", sa.String(length=200), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("meeting_sessions", "title")
