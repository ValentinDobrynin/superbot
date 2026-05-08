"""business mode (observer-only)

Revision ID: 20260508_0810_c3d5e7f9a1b3
Revises: 20260508_0445_b2c4d6e8f0a2
Create Date: 2026-05-08 08:10:00.000000

Adds infrastructure for FEATURE-004 (Telegram Business mode, observer):

- ``business_connections`` table — one row per Telegram Business connection
  (audit trail; on disconnect we flip ``is_enabled=False`` instead of deleting).
- ``chats.business_connection_id`` — nullable FK that disambiguates a
  ``tg_type='private'`` chat opened via Business Mode from the owner-bot DM
  (which is never persisted as a Chat row).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "20260508_0810_c3d5e7f9a1b3"
down_revision: Union[str, None] = "20260508_0445_b2c4d6e8f0a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "business_connections",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("user_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("can_reply", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("rights", JSONB(), nullable=True),
        sa.Column(
            "connected_at",
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

    op.add_column(
        "chats",
        sa.Column("business_connection_id", sa.String(length=64), nullable=True),
    )
    op.create_foreign_key(
        "chats_business_connection_id_fkey",
        "chats",
        "business_connections",
        ["business_connection_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_chats_business_connection_id",
        "chats",
        ["business_connection_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_chats_business_connection_id", table_name="chats")
    op.drop_constraint("chats_business_connection_id_fkey", "chats", type_="foreignkey")
    op.drop_column("chats", "business_connection_id")
    op.drop_table("business_connections")
