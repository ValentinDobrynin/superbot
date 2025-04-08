"""create_tables

Revision ID: 20250406_1820_9e1f012a388e
Revises: 
Create Date: 2024-04-06 18:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision: str = '20250406_1820_9e1f012a388e'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create chats table
    op.create_table(
        'chats',
        sa.Column('id', postgresql.UUID(), nullable=False),
        sa.Column('name', sa.String(), nullable=True),
        sa.Column('description', sa.String(), nullable=True),
        sa.Column('type', sa.String(), nullable=False),
        sa.Column('is_silent', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('smart_mode', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('response_probability', sa.Float(), nullable=False, server_default='0.5'),
        sa.Column('importance_threshold', sa.Float(), nullable=False, server_default='0.5'),
        sa.Column('last_summary_timestamp', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint("type IN ('WORK', 'FRIENDLY', 'MIXED')", name='chat_type_check')
    )
    
    # Create styles table
    op.create_table(
        'styles',
        sa.Column('id', postgresql.UUID(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create message_threads table
    op.create_table(
        'message_threads',
        sa.Column('id', postgresql.UUID(), nullable=False),
        sa.Column('chat_id', postgresql.UUID(), nullable=False),
        sa.Column('name', sa.String(), nullable=True),
        sa.Column('description', sa.String(), nullable=True),
        sa.Column('topic', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.ForeignKeyConstraint(['chat_id'], ['chats.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create messages table
    op.create_table(
        'messages',
        sa.Column('id', postgresql.UUID(), nullable=False),
        sa.Column('message_id', sa.Integer(), nullable=False),
        sa.Column('chat_id', postgresql.UUID(), nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('text', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('was_responded', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('thread_id', postgresql.UUID(), nullable=True),
        sa.ForeignKeyConstraint(['chat_id'], ['chats.id'], ),
        sa.ForeignKeyConstraint(['thread_id'], ['message_threads.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create message_contexts table
    op.create_table(
        'message_contexts',
        sa.Column('id', postgresql.UUID(), nullable=False),
        sa.Column('message_id', postgresql.UUID(), nullable=False),
        sa.Column('thread_id', postgresql.UUID(), nullable=False),
        sa.Column('context_summary', sa.String(), nullable=True),
        sa.Column('importance_score', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['message_id'], ['messages.id'], ),
        sa.ForeignKeyConstraint(['thread_id'], ['message_threads.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create tags table
    op.create_table(
        'tags',
        sa.Column('id', postgresql.UUID(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.String(), nullable=True),
        sa.Column('is_system', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name')
    )
    
    # Create message_tags table
    op.create_table(
        'message_tags',
        sa.Column('id', postgresql.UUID(), nullable=False),
        sa.Column('message_id', postgresql.UUID(), nullable=False),
        sa.Column('tag_id', postgresql.UUID(), nullable=False),
        sa.Column('is_auto', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('confidence', sa.Float(), nullable=False, server_default='1.0'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['message_id'], ['messages.id'], ),
        sa.ForeignKeyConstraint(['tag_id'], ['tags.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create thread_relations table
    op.create_table(
        'thread_relations',
        sa.Column('thread_id', postgresql.UUID(), nullable=False),
        sa.Column('related_thread_id', postgresql.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['thread_id'], ['message_threads.id'], ),
        sa.ForeignKeyConstraint(['related_thread_id'], ['message_threads.id'], ),
        sa.PrimaryKeyConstraint('thread_id', 'related_thread_id')
    )
    
    # Create message_stats table
    op.create_table(
        'message_stats',
        sa.Column('id', postgresql.UUID(), nullable=False),
        sa.Column('chat_id', postgresql.UUID(), nullable=False),
        sa.Column('period', sa.String(), nullable=False),
        sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False),
        sa.Column('message_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('user_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('avg_length', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('emoji_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('sticker_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('top_emojis', postgresql.JSON(), nullable=True),
        sa.Column('top_stickers', postgresql.JSON(), nullable=True),
        sa.Column('top_words', postgresql.JSON(), nullable=True),
        sa.Column('top_topics', postgresql.JSON(), nullable=True),
        sa.Column('most_active_hour', sa.Integer(), nullable=True),
        sa.Column('most_active_day', sa.String(), nullable=True),
        sa.Column('activity_trend', postgresql.JSON(), nullable=True),
        sa.ForeignKeyConstraint(['chat_id'], ['chats.id'], ),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    # Drop all tables in reverse order
    op.drop_table('message_stats')
    op.drop_table('thread_relations')
    op.drop_table('message_tags')
    op.drop_table('tags')
    op.drop_table('message_contexts')
    op.drop_table('messages')
    op.drop_table('message_threads')
    op.drop_table('styles')
    op.drop_table('chats') 