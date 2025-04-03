"""add last summary timestamp

Revision ID: add_last_summary_timestamp
Revises: previous_migration
Create Date: 2024-04-03 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from datetime import datetime

# revision identifiers, used by Alembic.
revision = 'add_last_summary_timestamp'
down_revision = 'previous_migration'  # Replace with your previous migration ID
branch_labels = None
depends_on = None

def upgrade():
    # Add last_summary_timestamp column
    op.add_column('chats', sa.Column('last_summary_timestamp', sa.DateTime(), nullable=True))

def downgrade():
    # Remove last_summary_timestamp column
    op.drop_column('chats', 'last_summary_timestamp') 