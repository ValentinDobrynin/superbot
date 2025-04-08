"""add_last_summary_timestamp_to_chats

Revision ID: 20250407_0623_add_last_summary_timestamp_to_chats
Revises: 20250406_2029_add_response_probability_to_chats
Create Date: 2024-04-07 06:23:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20250407_0623_add_last_summary_timestamp_to_chats'
down_revision: Union[str, None] = '20250406_2029_add_response_probability_to_chats'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add last_summary_timestamp column to chats table
    op.add_column('chats', sa.Column('last_summary_timestamp', sa.DateTime(), nullable=True))


def downgrade() -> None:
    # Remove last_summary_timestamp column from chats table
    op.drop_column('chats', 'last_summary_timestamp') 