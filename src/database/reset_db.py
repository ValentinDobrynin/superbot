import asyncio
import os
import sys

# Add the current directory to Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from src.database.database import reset_db

async def main():
    """Reset the database."""
    print("🔄 Resetting database...")
    await reset_db()

if __name__ == "__main__":
    asyncio.run(main()) 