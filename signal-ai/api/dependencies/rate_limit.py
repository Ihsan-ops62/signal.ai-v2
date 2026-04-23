import time
from fastapi import HTTPException
from infrastructure.database.mongodb import MongoDB

async def check_rate_limit(username: str, platform: str, max_requests: int = 1, window_seconds: int = 60) -> bool:
    """
    Check and enforce rate limiting for a user on a specific platform.
    Returns True if allowed, False otherwise.
    """
    coll = MongoDB.get_collection("user_rate_limits")
    now = time.time()
    doc = await coll.find_one({"username": username, "platform": platform})
    
    if not doc:
        await coll.insert_one({
            "username": username,
            "platform": platform,
            "last_post_time": 0,
            "count": 0,
            "last_reset": now,
        })
        return True
    
    if now - doc.get("last_reset", 0) > window_seconds:
        await coll.update_one(
            {"_id": doc["_id"]},
            {"$set": {"count": 0, "last_reset": now}}
        )
        return True
    
    if doc.get("count", 0) >= max_requests:
        return False
    
    await coll.update_one(
        {"_id": doc["_id"]},
        {"$inc": {"count": 1}, "$set": {"last_post_time": now}}
    )
    return True