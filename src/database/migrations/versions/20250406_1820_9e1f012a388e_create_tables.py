"""create_tables

Revision ID: 9e1f012a388e
Revises: 
Create Date: 2024-04-06 18:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision: str = '9e1f012a388e'
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
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['chat_id'], ['chats.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create messages table
    op.create_table(
        'messages',
        sa.Column('id', postgresql.UUID(), nullable=False),
        sa.Column('thread_id', postgresql.UUID(), nullable=False),
        sa.Column('role', sa.String(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['thread_id'], ['message_threads.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create message_contexts table
    op.create_table(
        'message_contexts',
        sa.Column('id', postgresql.UUID(), nullable=False),
        sa.Column('message_id', postgresql.UUID(), nullable=False),
        sa.Column('context_type', sa.String(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['message_id'], ['messages.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create tags table
    op.create_table(
        'tags',
        sa.Column('id', postgresql.UUID(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create message_tags table
    op.create_table(
        'message_tags',
        sa.Column('message_id', postgresql.UUID(), nullable=False),
        sa.Column('tag_id', postgresql.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['message_id'], ['messages.id'], ),
        sa.ForeignKeyConstraint(['tag_id'], ['tags.id'], ),
        sa.PrimaryKeyConstraint('message_id', 'tag_id')
    )
    
    # Create thread_relations table
    op.create_table(
        'thread_relations',
        sa.Column('parent_thread_id', postgresql.UUID(), nullable=False),
        sa.Column('child_thread_id', postgresql.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['child_thread_id'], ['message_threads.id'], ),
        sa.ForeignKeyConstraint(['parent_thread_id'], ['message_threads.id'], ),
        sa.PrimaryKeyConstraint('parent_thread_id', 'child_thread_id')
    )
    
    # Create message_stats table
    op.create_table(
        'message_stats',
        sa.Column('id', postgresql.UUID(), nullable=False),
        sa.Column('message_id', postgresql.UUID(), nullable=False),
        sa.Column('tokens_used', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['message_id'], ['messages.id'], ),
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