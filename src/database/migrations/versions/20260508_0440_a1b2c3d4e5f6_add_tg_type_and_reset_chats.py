"""add tg_type to chats and reset all data tables

Revision ID: 20260508_0440_a1b2c3d4e5f6
Revises: 20250408_0313_39084349b1d4
Create Date: 2026-05-08 04:40:00.000000

This migration is part of FEATURE-003 (ignore Telegram channels) and
also performs a one-shot DATA RESET requested by the owner: all data
tables are TRUNCATEd CASCADE so the bot starts from a clean slate.

Why TRUNCATE here: the user explicitly asked to wipe state when we
introduced channel filtering. Doing it inside the migration keeps it
audit-tracked in alembic_version (one-shot, won't re-run).

Schema change: chats.tg_type — Telegram-side chat type, separate from
chats.type (which is our internal style enum WORK/FRIENDLY/MIXED).
Allowed values: private, group, supergroup, channel.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260508_0440_a1b2c3d4e5f6"
down_revision: Union[str, None] = "20250408_0313_39084349b1d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_DATA_TABLES = (
    "message_tags",
    "tags",
    "message_contexts",
    "thread_relations",
    "message_threads",
    "message_stats",
    "messages",
    "styles",
    "chats",
)


def upgrade() -> None:
    op.execute("TRUNCATE " + ", ".join(_DATA_TABLES) + " RESTART IDENTITY CASCADE")

    op.add_column(
        "chats",
        sa.Column("tg_type", sa.String(length=16), nullable=False),
    )
    op.create_check_constraint(
        "chats_tg_type_check",
        "chats",
        "tg_type IN ('private', 'group', 'supergroup', 'channel')",
    )


def downgrade() -> None:
    op.drop_constraint("chats_tg_type_check", "chats", type_="check")
    op.drop_column("chats", "tg_type")
