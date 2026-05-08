"""Async SQLAlchemy engine, session factory and helpers."""

from __future__ import annotations

import logging
from typing import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.config import settings

from .base import Base
from .models import *  # noqa: F401,F403 — register models with Base

logger = logging.getLogger(__name__)

engine = create_async_engine(settings.get_async_database_url(), echo=False)

async_session = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def reset_db() -> None:
    """Drop and recreate all tables. DESTRUCTIVE — for local dev only."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
        logger.info("Database reset successfully")


async def init_db() -> None:
    """Create tables if the schema is empty."""
    async with engine.begin() as conn:
        result = await conn.execute(
            text(
                "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_schema = 'public')"
            )
        )
        exists = result.scalar()
        if not exists:
            await conn.run_sync(Base.metadata.create_all)
            logger.info("Database tables created successfully")
        else:
            logger.info("Database tables already exist; nothing to do")


async def get_session() -> AsyncIterator[AsyncSession]:
    """Yield an ``AsyncSession`` and close it on exit."""
    async with async_session() as session:
        yield session
