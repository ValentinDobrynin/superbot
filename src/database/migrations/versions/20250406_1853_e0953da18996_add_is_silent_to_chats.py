"""add_is_silent_to_chats

Revision ID: 20250406_1853_e0953da18996
Revises: 20250406_1820_9e1f012a388e
Create Date: 2024-04-06 18:53:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20250406_1853_e0953da18996'
down_revision: Union[str, None] = '20250406_1820_9e1f012a388e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add is_silent column to chats table
    op.add_column('chats', sa.Column('is_silent', sa.Boolean(), nullable=False, server_default='true'))


def downgrade() -> None:
    # Remove is_silent column from chats table
    op.drop_column('chats', 'is_silent') 