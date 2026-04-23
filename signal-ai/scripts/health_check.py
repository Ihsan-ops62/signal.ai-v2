#!/usr/bin/env python

import asyncio
import sys
import httpx
from core.config import config

async def check_ollama():
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{config.OLLAMA_BASE_URL}/api/tags")
            return resp.status_code == 200
    except Exception:
        return False

async def check_mongodb():
    from infrastructure.database.mongodb import MongoDB
    try:
        await MongoDB.connect()
        await MongoDB.get_db().command("ping")
        return True
    except Exception:
        return False

async def main():
    results = await asyncio.gather(
        check_ollama(),
        check_mongodb(),
        return_exceptions=True
    )
    ollama_ok, mongo_ok = results
    if ollama_ok and mongo_ok:
        print("All services healthy")
        sys.exit(0)
    else:
        if not ollama_ok:
            print("Ollama is not healthy")
        if not mongo_ok:
            print("MongoDB is not healthy")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())