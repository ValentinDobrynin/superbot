import asyncio
import logging
from .add_is_silent_column import upgrade as upgrade_silent, downgrade as downgrade_silent
from .update_chat_id_to_bigint import upgrade as upgrade_bigint, downgrade as downgrade_bigint

logger = logging.getLogger(__name__)

async def run_migrations():
    """Run all database migrations."""
    try:
        logger.info("Starting database migrations...")
        await upgrade_silent()
        await upgrade_bigint()
        logger.info("Database migrations completed successfully")
    except Exception as e:
        logger.error(f"Error running migrations: {str(e)}")
        raise

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_migrations()) 