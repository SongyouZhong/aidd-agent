"""add session_files table

Revision ID: 0003_session_files
Revises: 0002_target_discovery
Create Date: 2026-05-05

"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0003_session_files"
down_revision: Union[str, Sequence[str], None] = "0002_target_discovery"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "session_files",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("original_filename", sa.String(length=500), nullable=False),
        sa.Column("mime_type", sa.String(length=128), nullable=False),
        sa.Column("size", sa.BigInteger, nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("s3_key", sa.String(length=1024), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_session_files_session_id", "session_files", ["session_id"])
    op.create_index("ix_session_files_user_id", "session_files", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_session_files_user_id", table_name="session_files")
    op.drop_index("ix_session_files_session_id", table_name="session_files")
    op.drop_table("session_files")
