import logging
import time
import asyncio
from typing import Optional

from cryptography.fernet import Fernet
from infrastructure.database.mongodb import MongoDB
from core.config import config

logger = logging.getLogger(__name__)

# Key is guaranteed to be valid by config
_fernet = Fernet(config.TOKEN_ENCRYPTION_KEY.encode())

def _encrypt(value: str) -> str:
    return _fernet.encrypt(value.encode()).decode()

def _decrypt(value: str) -> str:
    return _fernet.decrypt(value.encode()).decode()

async def store_token(username: str, platform: str, token_data: dict) -> None:
    username = username.lower()
    coll = MongoDB.get_collection("user_tokens")
    encrypted = {
        k: _encrypt(str(v)) if isinstance(v, str) else v
        for k, v in token_data.items()
    }
    encrypted["username"] = username
    encrypted["platform"] = platform
    encrypted["stored_at"] = time.time()
    await coll.update_one(
        {"username": username, "platform": platform},
        {"$set": encrypted},
        upsert=True,
    )
    logger.info("Stored %s token for user %s", platform, username)

async def load_token(username: str, platform: str) -> Optional[dict]:
    username = username.lower()
    coll = MongoDB.get_collection("user_tokens")
    doc = await coll.find_one({"username": username, "platform": platform})
    if not doc:
        return None
    result = {}
    skip = {"_id", "username", "platform", "stored_at"}
    for k, v in doc.items():
        if k in skip:
            result[k] = v
            continue
        if isinstance(v, str):
            try:
                result[k] = _decrypt(v)
            except Exception:
                result[k] = v
        else:
            result[k] = v
    return result

async def delete_token(username: str, platform: str) -> None:
    username = username.lower()
    coll = MongoDB.get_collection("user_tokens")
    await coll.delete_one({"username": username, "platform": platform})
    logger.info("Deleted %s token for user %s", platform, username)

_refresh_locks: dict[str, asyncio.Lock] = {}

async def get_access_token(username: str, platform: str) -> Optional[str]:
    username = username.lower()
    key = f"{username}:{platform}"
    lock = _refresh_locks.setdefault(key, asyncio.Lock())
    async with lock:
        record = await load_token(username, platform)
        if not record:
            return None

        access_token = record.get("access_token")
        expires_at = record.get("expires_at")
        refresh_token = record.get("refresh_token")

        if expires_at and float(expires_at) > time.time() + 60:
            return access_token

        if refresh_token and platform == "linkedin":
            refreshed = await _refresh_linkedin_token(username, refresh_token)
            if refreshed:
                return refreshed

        return access_token

async def _refresh_linkedin_token(username: str, refresh_token: str) -> Optional[str]:
    import httpx

    if not config.LINKEDIN_CLIENT_ID or not config.LINKEDIN_CLIENT_SECRET:
        return None
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                "https://www.linkedin.com/oauth/v2/accessToken",
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": config.LINKEDIN_CLIENT_ID,
                    "client_secret": config.LINKEDIN_CLIENT_SECRET,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        if resp.status_code == 200:
            data = resp.json()
            new_token = data.get("access_token")
            expires_in = data.get("expires_in", 5184000)
            new_refresh = data.get("refresh_token", refresh_token)
            if new_token:
                await store_token(username, "linkedin", {
                    "access_token": new_token,
                    "refresh_token": new_refresh,
                    "expires_at": str(time.time() + expires_in),
                })
                return new_token
    except Exception as exc:
        logger.warning("LinkedIn token refresh failed: %s", exc)
    return None