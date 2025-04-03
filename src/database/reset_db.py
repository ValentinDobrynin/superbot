import asyncio
import os
from src.database.database import reset_db

async def main():
    """Reset the database."""
    print("🔄 Resetting database...")
    await reset_db()

if __name__ == "__main__":
    asyncio.run(main()) 