#!/usr/bin/env python
import asyncio
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from infrastructure.database.mongodb import MongoDB
from core.config import config

async def run_migrations():
    await MongoDB.connect()
    db = MongoDB.get_db()
    
    # Create collections if not exist (MongoDB creates on first use)
    # Additional migration logic can go here
    print("Migrations completed successfully.")

if __name__ == "__main__":
    asyncio.run(run_migrations())