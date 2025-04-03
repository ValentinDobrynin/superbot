from sqlalchemy import text
from ..config import engine
import logging

logger = logging.getLogger(__name__)

async def upgrade():
    """Update chat_id columns to BIGINT type."""
    try:
        async with engine.begin() as conn:
            # Update chats table
            await conn.execute(
                text("""
                ALTER TABLE chats 
                ALTER COLUMN chat_id TYPE BIGINT;
                """)
            )
            
            # Update messages table
            await conn.execute(
                text("""
                ALTER TABLE messages 
                ALTER COLUMN chat_id TYPE BIGINT;
                """)
            )
            
        logger.info("Successfully updated chat_id columns to BIGINT type")
    except Exception as e:
        logger.error(f"Error updating chat_id columns: {str(e)}")
        raise

async def downgrade():
    """Revert chat_id columns back to INTEGER type."""
    try:
        async with engine.begin() as conn:
            # Revert messages table first (due to foreign key constraint)
            await conn.execute(
                text("""
                ALTER TABLE messages 
                ALTER COLUMN chat_id TYPE INTEGER;
                """)
            )
            
            # Revert chats table
            await conn.execute(
                text("""
                ALTER TABLE chats 
                ALTER COLUMN chat_id TYPE INTEGER;
                """)
            )
            
        logger.info("Successfully reverted chat_id columns to INTEGER type")
    except Exception as e:
        logger.error(f"Error reverting chat_id columns: {str(e)}")
        raise 