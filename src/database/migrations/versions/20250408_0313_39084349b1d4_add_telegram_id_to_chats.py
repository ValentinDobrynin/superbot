"""add telegram_id to chats

Revision ID: 20250408_0313_39084349b1d4
Revises: 20250406_1820_9e1f012a388e
Create Date: 2025-04-08 03:13:39.084349

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20250408_0313_39084349b1d4'
down_revision: Union[str, None] = '20250406_1820_9e1f012a388e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add telegram_id column to chats table
    op.add_column('chats', sa.Column('telegram_id', sa.BigInteger(), nullable=False))
    # Add unique constraint
    op.create_unique_constraint('uq_chats_telegram_id', 'chats', ['telegram_id'])


def downgrade() -> None:
    # Remove unique constraint
    op.drop_constraint('uq_chats_telegram_id', 'chats', type_='unique')
    # Remove telegram_id column
    op.drop_column('chats', 'telegram_id') 