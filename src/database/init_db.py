"""CLI helper: drop & recreate all tables. Useful for local dev only."""

from __future__ import annotations

import asyncio
import logging
import os

from sqlalchemy.ext.asyncio import create_async_engine

from src.config import settings
from src.database.base import Base
from src.database.models import *  # noqa: F401,F403 — register models with Base

logger = logging.getLogger(__name__)


async def init_db() -> None:
    if not settings.DATABASE_URL and not os.getenv("DATABASE_URL"):
        raise ValueError("DATABASE_URL is not set")

    engine = create_async_engine(settings.get_async_database_url(), echo=False)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database initialised (drop + create)")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(init_db())
