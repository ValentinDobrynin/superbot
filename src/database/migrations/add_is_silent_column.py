from sqlalchemy import text
from ..config import engine
import logging

logger = logging.getLogger(__name__)

async def upgrade():
    """Add is_silent column to chats table."""
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text("""
                ALTER TABLE chats 
                ADD COLUMN IF NOT EXISTS is_silent BOOLEAN DEFAULT FALSE;
                """)
            )
        logger.info("Successfully added is_silent column to chats table")
    except Exception as e:
        logger.error(f"Error adding is_silent column: {str(e)}")
        raise

async def downgrade():
    """Remove is_silent column from chats table."""
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text("""
                ALTER TABLE chats 
                DROP COLUMN IF EXISTS is_silent;
                """)
            )
        logger.info("Successfully removed is_silent column from chats table")
    except Exception as e:
        logger.error(f"Error removing is_silent column: {str(e)}")
        raise 