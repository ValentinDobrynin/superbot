#!/usr/bin/env python3
import os
import sys

# Add the project root directory to Python path
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

from src.database.reset_db import main
import asyncio

if __name__ == "__main__":
    asyncio.run(main()) 