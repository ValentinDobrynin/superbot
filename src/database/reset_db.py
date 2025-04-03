import asyncio
import os
import sys

# Add the project root directory to Python path
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, project_root)

from src.database.database import reset_db

async def main():
    """Reset the database."""
    print("🔄 Resetting database...")
    await reset_db()

if __name__ == "__main__":
    asyncio.run(main()) 