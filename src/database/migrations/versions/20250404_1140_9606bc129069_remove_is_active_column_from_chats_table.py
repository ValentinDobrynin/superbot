"""remove is_active column from chats table

Revision ID: 20250404_1140_9606bc129069_remove_is_active_column_from_chats_table
Revises: 2aec5090bdd8
Create Date: 2025-04-04 11:40:44.675080+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20250404_1140_9606bc129069_remove_is_active_column_from_chats_table'
down_revision: Union[str, None] = '2aec5090bdd8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column('chats', 'is_active')


def downgrade() -> None:
    op.add_column('chats', sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true')) 