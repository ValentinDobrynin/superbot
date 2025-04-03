import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text

from src.config import settings
from .base import Base
from .models import *  # Import all models to register them with Base

# Create async engine
engine = create_async_engine(settings.DATABASE_URL, echo=True)

# Create async session factory
async_session = sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)

async def reset_db():
    """Reset the database by dropping all tables and creating new ones."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
        print("✅ Database reset successfully!")

async def init_db():
    """Initialize the database by creating tables if they don't exist."""
    async with engine.begin() as conn:
        # Check if tables exist using raw SQL
        result = await conn.run_sync(
            lambda sync_conn: sync_conn.execute(
                text("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables 
                        WHERE table_schema = 'public'
                    );
                """)
            ).scalar()
        )
        
        # Create tables only if they don't exist
        if not result:
            await conn.run_sync(Base.metadata.create_all)
            print("✅ Database tables created successfully!")
        else:
            print("⚠️ Database tables already exist. If you need to reset the database, use reset_db()")

async def get_session() -> AsyncSession:
    """Get database session."""
    async with async_session() as session:
        yield session 