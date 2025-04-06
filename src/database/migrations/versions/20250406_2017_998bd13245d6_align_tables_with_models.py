"""align_tables_with_models

Revision ID: 998bd13245d6
Revises: 0314d7c73d0b
Create Date: 2024-04-06 20:17:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision: str = '998bd13245d6'
down_revision: Union[str, None] = '0314d7c73d0b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop existing tables that need to be recreated
    op.drop_table('message_stats')
    op.drop_table('thread_relations')
    op.drop_table('message_tags')
    op.drop_table('tags')
    op.drop_table('message_contexts')
    op.drop_table('styles')
    
    # Drop existing enum type if it exists
    connection = op.get_bind()
    connection.execute(text('DROP TYPE IF EXISTS chattype CASCADE'))
    
    # Recreate styles table with correct schema
    op.create_table(
        'styles',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('chat_type', sa.Enum('WORK', 'FRIENDLY', 'MIXED', name='chattype'), nullable=False),
        sa.Column('prompt_template', sa.String(), nullable=True),
        sa.Column('last_updated', sa.DateTime(), nullable=False),
        sa.Column('training_data', sa.String(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('chat_type')
    )
    
    # Recreate message_contexts table with correct message_id type
    op.create_table(
        'message_contexts',
        sa.Column('id', postgresql.UUID(), nullable=False),
        sa.Column('message_id', postgresql.UUID(), nullable=True),
        sa.Column('thread_id', postgresql.UUID(), nullable=False),
        sa.Column('context_summary', sa.String(), nullable=True),
        sa.Column('importance_score', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['message_id'], ['messages.id'], ),
        sa.ForeignKeyConstraint(['thread_id'], ['message_threads.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Recreate tags table
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
    
    # Recreate message_tags table with correct message_id type
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
    
    # Recreate thread_relations table without created_at
    op.create_table(
        'thread_relations',
        sa.Column('thread_id', postgresql.UUID(), nullable=False),
        sa.Column('related_thread_id', postgresql.UUID(), nullable=False),
        sa.ForeignKeyConstraint(['thread_id'], ['message_threads.id'], ),
        sa.ForeignKeyConstraint(['related_thread_id'], ['message_threads.id'], ),
        sa.PrimaryKeyConstraint('thread_id', 'related_thread_id')
    )
    
    # Recreate message_stats table with correct id type
    op.create_table(
        'message_stats',
        sa.Column('id', sa.Integer(), nullable=False),
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
    op.drop_table('styles')
    
    # Drop enum type
    connection = op.get_bind()
    connection.execute(text('DROP TYPE IF EXISTS chattype CASCADE'))
    
    # Recreate tables with previous schema
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