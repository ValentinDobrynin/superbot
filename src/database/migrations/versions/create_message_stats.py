"""create message_stats table

Revision ID: create_message_stats
Revises: create_chat_stats
Create Date: 2024-04-04 19:35:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'create_message_stats'
down_revision: Union[str, None] = 'create_chat_stats'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('message_stats',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('chat_id', sa.Integer(), nullable=False),
        sa.Column('period', sa.String(), nullable=False),
        sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False),
        sa.Column('message_count', sa.Integer(), nullable=False),
        sa.Column('user_count', sa.Integer(), nullable=False),
        sa.Column('avg_length', sa.Float(), nullable=False),
        sa.Column('emoji_count', sa.Integer(), nullable=False),
        sa.Column('sticker_count', sa.Integer(), nullable=False),
        sa.Column('top_emojis', postgresql.JSONB(), nullable=False),
        sa.Column('top_stickers', postgresql.JSONB(), nullable=False),
        sa.Column('top_words', postgresql.JSONB(), nullable=False),
        sa.Column('top_topics', postgresql.JSONB(), nullable=False),
        sa.Column('most_active_hour', sa.Integer(), nullable=False),
        sa.Column('most_active_day', sa.String(), nullable=False),
        sa.Column('activity_trend', sa.String(), nullable=False),
        sa.ForeignKeyConstraint(['chat_id'], ['chats.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_message_stats_chat_id'), 'message_stats', ['chat_id'], unique=False)
    op.create_index(op.f('ix_message_stats_period'), 'message_stats', ['period'], unique=False)
    op.create_index(op.f('ix_message_stats_timestamp'), 'message_stats', ['timestamp'], unique=False)
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index(op.f('ix_message_stats_timestamp'), table_name='message_stats')
    op.drop_index(op.f('ix_message_stats_period'), table_name='message_stats')
    op.drop_index(op.f('ix_message_stats_chat_id'), table_name='message_stats')
    op.drop_table('message_stats')
    # ### end Alembic commands ### 