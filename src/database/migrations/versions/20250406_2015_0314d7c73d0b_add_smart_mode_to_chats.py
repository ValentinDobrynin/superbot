"""add_smart_mode_to_chats

Revision ID: 20250406_2015_0314d7c73d0b
Revises: 20250406_1857_40b390b3ab9e
Create Date: 2024-04-06 20:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20250406_2015_0314d7c73d0b'
down_revision: Union[str, None] = '20250406_1857_40b390b3ab9e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add smart_mode column to chats table
    op.add_column('chats', sa.Column('smart_mode', sa.Boolean(), nullable=False, server_default='false'))


def downgrade() -> None:
    # Remove smart_mode column from chats table
    op.drop_column('chats', 'smart_mode') 