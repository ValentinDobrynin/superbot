from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from .models import Base
from .config import engine, async_session
from .migrations.run_migrations import run_migrations
import logging

logger = logging.getLogger(__name__)

async def init_db():
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database initialized successfully")
        
        # Run migrations
        await run_migrations()
        logger.info("Database migrations completed")
    except Exception as e:
        logger.error(f"Error initializing database: {str(e)}")
        raise

async def get_session() -> AsyncSession:
    """Get a new database session."""
    try:
        session = async_session()
        return session
    except Exception as e:
        logger.error(f"Error creating database session: {str(e)}")
        raise 