import asyncio
import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from src.database.models import Base
from src.config import settings

async def init_db():
    """Initialize the database by creating all tables."""
    # Get database URL from environment
    database_url = os.getenv('DATABASE_URL')
    if not database_url:
        raise ValueError("DATABASE_URL environment variable is not set")
    
    # Create async engine
    engine = create_async_engine(database_url, echo=True)
    
    # Create all tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)  # Drop all existing tables
        await conn.run_sync(Base.metadata.create_all)  # Create all tables
    
    await engine.dispose()
    print("✅ Database initialized successfully!")

if __name__ == "__main__":
    asyncio.run(init_db()) 