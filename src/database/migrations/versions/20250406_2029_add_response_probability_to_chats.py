"""add_response_probability_to_chats

Revision ID: 20250406_2029_add_response_probability_to_chats
Revises: 20250406_2017_998bd13245d6
Create Date: 2024-04-06 20:29:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20250406_2029_add_response_probability_to_chats'
down_revision: Union[str, None] = '20250406_2017_998bd13245d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add response_probability and importance_threshold columns to chats table
    op.add_column('chats', sa.Column('response_probability', sa.Float(), nullable=False, server_default='1.0'))
    op.add_column('chats', sa.Column('importance_threshold', sa.Float(), nullable=False, server_default='0.5'))


def downgrade() -> None:
    # Remove response_probability and importance_threshold columns from chats table
    op.drop_column('chats', 'response_probability')
    op.drop_column('chats', 'importance_threshold') 