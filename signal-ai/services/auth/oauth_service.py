import logging
import secrets
import time
import asyncio
from typing import Optional
from urllib.parse import urlencode

import httpx
from cryptography.fernet import Fernet

from infrastructure.database.mongodb import MongoDB
from core.config import config

logger = logging.getLogger(__name__)

#  FIXED: Key validation now happens in config.py at import time
# If TOKEN_ENCRYPTION_KEY is invalid or missing, application will not start
_fernet = Fernet(config.TOKEN_ENCRYPTION_KEY.encode())

def _encrypt(value: str) -> str:
    return _fernet.encrypt(value.encode()).decode()

def _decrypt(value: str) -> str:
    return _fernet.decrypt(value.encode()).decode()

# LinkedIn OAuth Config
LINKEDIN_CLIENT_ID     = config.LINKEDIN_CLIENT_ID
LINKEDIN_CLIENT_SECRET = config.LINKEDIN_CLIENT_SECRET
LINKEDIN_REDIRECT_URI  = config.LINKEDIN_REDIRECT_URI
LINKEDIN_SCOPES        = ["openid", "profile", "w_member_social"]
LINKEDIN_AUTH_URL      = "https://www.linkedin.com/oauth/v2/authorization"
LINKEDIN_TOKEN_URL     = "https://www.linkedin.com/oauth/v2/accessToken"

# Token Storage
async def store_token(username: str, platform: str, token_data: dict) -> None:
    username = username.lower()
    coll = MongoDB.get_collection("user_tokens")
    encrypted = {
        k: _encrypt(str(v)) if isinstance(v, str) else v
        for k, v in token_data.items()
    }
    encrypted["username"]  = username
    encrypted["platform"]  = platform
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

# Refresh locks
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
        expires_at   = record.get("expires_at")
        refresh_token = record.get("refresh_token")

        if expires_at and float(expires_at) > time.time() + 60:
            return access_token

        if refresh_token and platform == "linkedin":
            refreshed = await _refresh_linkedin_token(username, refresh_token)
            if refreshed:
                return refreshed

        if refresh_token and platform == "twitter":
            # Defer to TwitterService to avoid circular import
            from services.social.twitter import TwitterService
            refreshed = await TwitterService.refresh_token(username, refresh_token)
            if refreshed:
                return refreshed

        return access_token

# OAuth State Management
_oauth_states: dict[str, tuple[str, float]] = {}
_STATE_TTL = 600

def create_oauth_state(username: str) -> str:
    state = secrets.token_urlsafe(32)
    _oauth_states[state] = (username, time.time())
    now = time.time()
    expired = [s for s, (_, t) in _oauth_states.items() if now - t > _STATE_TTL]
    for s in expired:
        _oauth_states.pop(s, None)
    return state

def validate_oauth_state(state: str) -> Optional[str]:
    entry = _oauth_states.pop(state, None)
    if not entry:
        return None
    username, created_at = entry
    if time.time() - created_at > _STATE_TTL:
        return None
    return username

# LinkedIn OAuth Flow
def get_linkedin_auth_url(state: str) -> str:
    if not LINKEDIN_CLIENT_ID:
        raise ValueError("LINKEDIN_CLIENT_ID is not configured.")
    params = {
        "response_type": "code",
        "client_id":     LINKEDIN_CLIENT_ID,
        "redirect_uri":  LINKEDIN_REDIRECT_URI,
        "state":         state,
        "scope":         " ".join(LINKEDIN_SCOPES),
    }
    return f"{LINKEDIN_AUTH_URL}?{urlencode(params)}"

async def exchange_linkedin_code(code: str, username: str) -> dict:
    if not LINKEDIN_CLIENT_ID or not LINKEDIN_CLIENT_SECRET:
        return {"success": False, "error": "LinkedIn OAuth not configured."}
    username = username.lower()
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                LINKEDIN_TOKEN_URL,
                data={
                    "grant_type":    "authorization_code",
                    "code":          code,
                    "redirect_uri":  LINKEDIN_REDIRECT_URI,
                    "client_id":     LINKEDIN_CLIENT_ID,
                    "client_secret": LINKEDIN_CLIENT_SECRET,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        if resp.status_code != 200:
            return {"success": False, "error": f"Token exchange failed: {resp.text}"}

        data          = resp.json()
        access_token  = data.get("access_token")
        expires_in    = data.get("expires_in", 5184000)
        refresh_token = data.get("refresh_token")

        if not access_token:
            return {"success": False, "error": "No access token in response"}

        person_urn = None
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                ui_resp = await client.get(
                    "https://api.linkedin.com/v2/userinfo",
                    headers={"Authorization": f"Bearer {access_token}"},
                )
            if ui_resp.status_code == 200:
                sub = ui_resp.json().get("sub")
                if sub:
                    person_urn = f"urn:li:person:{sub}"
        except Exception as exc:
            logger.warning("Could not fetch LinkedIn person URN: %s", exc)

        token_data = {
            "access_token":  access_token,
            "expires_at":    str(time.time() + expires_in),
            "token_type":    data.get("token_type", "Bearer"),
        }
        if refresh_token:
            token_data["refresh_token"] = refresh_token
        if person_urn:
            token_data["person_urn"] = person_urn

        await store_token(username, "linkedin", token_data)
        logger.info("LinkedIn token stored for user %s", username)
        return {"success": True}
    except Exception as exc:
        logger.error("exchange_linkedin_code failed: %s", exc)
        return {"success": False, "error": str(exc)}

async def _refresh_linkedin_token(username: str, refresh_token: str) -> Optional[str]:
    if not LINKEDIN_CLIENT_ID or not LINKEDIN_CLIENT_SECRET:
        return None
    username = username.lower()
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                LINKEDIN_TOKEN_URL,
                data={
                    "grant_type":    "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id":     LINKEDIN_CLIENT_ID,
                    "client_secret": LINKEDIN_CLIENT_SECRET,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        if resp.status_code == 200:
            data         = resp.json()
            new_token    = data.get("access_token")
            expires_in   = data.get("expires_in", 5184000)
            new_refresh  = data.get("refresh_token", refresh_token)
            if new_token:
                await store_token(username, "linkedin", {
                    "access_token":  new_token,
                    "refresh_token": new_refresh,
                    "expires_at":    str(time.time() + expires_in),
                })
                logger.info("LinkedIn token refreshed for user %s", username)
                return new_token
    except Exception as exc:
        logger.warning("LinkedIn token refresh failed: %s", exc)
    return None