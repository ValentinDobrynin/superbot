"""recreate tables

Revision ID: 20250404_2000_recreate_tables
Revises: 41548e099c5f
Create Date: 2024-04-04 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '20250404_2000_recreate_tables'
down_revision: Union[str, None] = '41548e099c5f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop existing tables
    op.drop_table('message_stats')
    op.drop_table('chats')
    
    # Create chats table
    op.create_table('chats',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('chat_id', sa.BigInteger(), nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('chat_type', sa.String(), nullable=False),
        sa.Column('is_silent', sa.Boolean(), nullable=False),
        sa.Column('response_probability', sa.Float(), nullable=False),
        sa.Column('smart_mode', sa.Boolean(), nullable=False),
        sa.Column('importance_threshold', sa.Float(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_summary_timestamp', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_chats_chat_id'), 'chats', ['chat_id'], unique=True)
    
    # Create message_stats table
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


def downgrade() -> None:
    op.drop_index(op.f('ix_message_stats_timestamp'), table_name='message_stats')
    op.drop_index(op.f('ix_message_stats_period'), table_name='message_stats')
    op.drop_index(op.f('ix_message_stats_chat_id'), table_name='message_stats')
    op.drop_table('message_stats')
    op.drop_index(op.f('ix_chats_chat_id'), table_name='chats')
    op.drop_table('chats') 