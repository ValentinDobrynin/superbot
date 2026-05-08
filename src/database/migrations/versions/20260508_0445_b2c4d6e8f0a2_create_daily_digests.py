"""create daily_digests table

Revision ID: 20260508_0445_b2c4d6e8f0a2
Revises: 20260508_0440_a1b2c3d4e5f6
Create Date: 2026-05-08 04:45:00.000000

Adds the audit table for FEATURE-002 (daily chat digest). One row per
calendar day (in Europe/Moscow), so we can:
- detect that today's digest was already sent (idempotent scheduler);
- keep some basic stats (chat_count, message_count) for future analysis.
"""

from typing import Sequence, Union
from uuid import uuid4

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "20260508_0445_b2c4d6e8f0a2"
down_revision: Union[str, None] = "20260508_0440_a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "daily_digests",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, default=uuid4),
        sa.Column("digest_date", sa.Date(), nullable=False, unique=True),
        sa.Column(
            "sent_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("chat_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("message_count", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_table("daily_digests")
