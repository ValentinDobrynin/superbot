#!/usr/bin/env python3
import os
import sys

# Add the current directory to Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(current_dir)

from src.database.reset_db import main
import asyncio

if __name__ == "__main__":
    asyncio.run(main()) 