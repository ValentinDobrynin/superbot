import asyncio
import logging
from .add_is_silent_column import upgrade, downgrade

logger = logging.getLogger(__name__)

async def run_migrations():
    """Run all database migrations."""
    try:
        logger.info("Starting database migrations...")
        await upgrade()
        logger.info("Database migrations completed successfully")
    except Exception as e:
        logger.error(f"Error running migrations: {str(e)}")
        raise

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_migrations()) 