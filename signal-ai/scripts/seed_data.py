#!/usr/bin/env python

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from infrastructure.database.mongodb import MongoDB
from api.dependencies.auth import get_password_hash

async def seed():
    await MongoDB.connect()
    coll = MongoDB.get_collection("users")
    
    # Create demo user if not exists
    demo_user = await coll.find_one({"username": "demo"})
    if not demo_user:
        await coll.insert_one({
            "username": "demo",
            "hashed_password": get_password_hash("demo123"),
            "disabled": False,
            "email": "demo@example.com"
        })
        print("Demo user created (username: demo, password: demo123)")
    else:
        print("Demo user already exists.")
    
    print("Seeding completed.")

if __name__ == "__main__":
    asyncio.run(seed())