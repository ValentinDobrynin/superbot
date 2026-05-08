"""glossary + commitments + events

Revision ID: 20260508_1300_d4e6f8a0c2b4
Revises: 20260508_0810_c3d5e7f9a1b3
Create Date: 2026-05-08 13:00:00.000000

Schema for the rich digest pipeline (FEATURE-007/008/009/010):

- ``chats.classification`` — owner-confirmed bucket for the chat:
  ``business`` / ``private`` / ``mixed`` / NULL (unclassified).
- ``commitments`` — what was promised in either direction. Persisted across
  digests so we can dedupe and let the owner mark items done/cancelled.
- ``events`` — dates / meetings extracted from the chat. Same lifecycle.
"""

from typing import Sequence, Union
from uuid import uuid4

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "20260508_1300_d4e6f8a0c2b4"
down_revision: Union[str, None] = "20260508_0810_c3d5e7f9a1b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "chats",
        sa.Column("classification", sa.String(length=16), nullable=True),
    )
    op.create_check_constraint(
        "chats_classification_check",
        "chats",
        "classification IS NULL OR classification IN ('business', 'private', 'mixed')",
    )

    op.create_table(
        "commitments",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, default=uuid4),
        sa.Column(
            "chat_id",
            UUID(as_uuid=True),
            sa.ForeignKey("chats.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("direction", sa.String(length=8), nullable=False),
        sa.Column("text", sa.String(), nullable=False),
        sa.Column("deadline_raw", sa.String(), nullable=True),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_urgent", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="open"),
        sa.Column("source_message_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "commitments_direction_check",
        "commitments",
        "direction IN ('from_me', 'to_me')",
    )
    op.create_check_constraint(
        "commitments_status_check",
        "commitments",
        "status IN ('open', 'done', 'cancelled')",
    )
    op.create_index("ix_commitments_chat_status", "commitments", ["chat_id", "status"])

    op.create_table(
        "events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, default=uuid4),
        sa.Column(
            "chat_id",
            UUID(as_uuid=True),
            sa.ForeignKey("chats.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("description", sa.String(), nullable=False),
        sa.Column("when_raw", sa.String(), nullable=True),
        sa.Column("when_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_urgent", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="upcoming"),
        sa.Column("source_message_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_check_constraint(
        "events_status_check",
        "events",
        "status IN ('upcoming', 'past', 'cancelled')",
    )
    op.create_index("ix_events_chat_status", "events", ["chat_id", "status"])
    op.create_index("ix_events_when_at", "events", ["when_at"])


def downgrade() -> None:
    op.drop_index("ix_events_when_at", table_name="events")
    op.drop_index("ix_events_chat_status", table_name="events")
    op.drop_constraint("events_status_check", "events", type_="check")
    op.drop_table("events")

    op.drop_index("ix_commitments_chat_status", table_name="commitments")
    op.drop_constraint("commitments_status_check", "commitments", type_="check")
    op.drop_constraint("commitments_direction_check", "commitments", type_="check")
    op.drop_table("commitments")

    op.drop_constraint("chats_classification_check", "chats", type_="check")
    op.drop_column("chats", "classification")
