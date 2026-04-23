import asyncio
import logging
import time
import secrets
import hashlib
import base64
from typing import Optional
from urllib.parse import urlencode

import httpx

from core.config import config
from infrastructure.database.mongodb import MongoDB
from services.auth.oauth_service import store_token, get_access_token, load_token

logger = logging.getLogger(__name__)

# Per‑user rate limiting
async def _check_rate_limit(username: str, platform: str = "twitter") -> bool:
    if not username:
        return True
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
    if now - doc.get("last_reset", 0) > 30:
        await coll.update_one({"_id": doc["_id"]}, {"$set": {"count": 0, "last_reset": now}})
        return True
    if doc.get("count", 0) >= 1:
        logger.info("Rate limit hit for user %s on Twitter", username)
        return False
    await coll.update_one({"_id": doc["_id"]}, {"$inc": {"count": 1}, "$set": {"last_post_time": now}})
    return True

_TWITTER_AUTH_URL  = "https://twitter.com/i/oauth2/authorize"
_TWITTER_TOKEN_URL = "https://api.twitter.com/2/oauth2/token"
_TWITTER_TWEETS_URL = "https://api.twitter.com/2/tweets"
_TWITTER_SCOPES    = ["tweet.read", "tweet.write", "users.read", "offline.access"]

_pkce_states: dict[str, tuple[str, str, float]] = {}
_STATE_TTL = 600

class TwitterService:

    @staticmethod
    async def _resolve_token(username: str) -> Optional[str]:
        if not username:
            return None
        username = username.lower()
        try:
            return await get_access_token(username, "twitter")
        except Exception as exc:
            logger.error("[Twitter] Token resolution error for %s: %s", username, exc)
            return None

    @staticmethod
    async def create_post(
        content: str,
        access_token: Optional[str] = None,
        username: Optional[str] = None,
    ) -> dict:
        if not content or not content.strip():
            return {"success": False, "error": "Tweet content cannot be empty."}

        token = access_token
        if not token and username:
            token = await TwitterService._resolve_token(username)

        if not token:
            return {
                "success": False,
                "error": "No Twitter access token available. Connect your account."
            }

        if username:
            allowed = await _check_rate_limit(username, "twitter")
            if not allowed:
                return {
                    "success": False,
                    "error": "Rate limit: Only one tweet per 30 seconds allowed."
                }

        if len(content) > 280:
            content = content[:277] + "..."

        result = await TwitterService._tweet_with_retry(token, content)
        if result["success"]:
            result["platform"] = "twitter"
        return result

    @staticmethod
    async def delete_post(
        tweet_id: str,
        access_token: Optional[str] = None,
        username: Optional[str] = None,
    ) -> dict:
        token = access_token
        if not token and username:
            token = await TwitterService._resolve_token(username)
        if not token:
            return {"success": False, "error": "No Twitter access token available."}

        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.delete(f"{_TWITTER_TWEETS_URL}/{tweet_id}", headers=headers)
            if resp.status_code == 200:
                deleted = resp.json().get("data", {}).get("deleted", False)
                if deleted:
                    logger.info("[Twitter] Tweet deleted: %s", tweet_id)
                    return {"success": True, "tweet_id": tweet_id}
            try:
                err = resp.json().get("detail", resp.text)
            except Exception:
                err = resp.text
            return {"success": False, "error": f"HTTP {resp.status_code}: {err}"}
        except Exception as exc:
            logger.error("[Twitter] delete_post failed: %s", exc)
            return {"success": False, "error": str(exc)}

    @staticmethod
    async def _tweet_with_retry(access_token: str, content: str, max_attempts: int = 3) -> dict:
        delay = 2.0
        headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
        payload = {"text": content}

        for attempt in range(1, max_attempts + 1):
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.post(_TWITTER_TWEETS_URL, headers=headers, json=payload)
                status = resp.status_code
                if status == 201:
                    tweet_id = resp.json().get("data", {}).get("id", "unknown")
                    logger.info("[Twitter] Tweet created: %s", tweet_id)
                    return {"success": True, "tweet_id": tweet_id}
                if status in (429, 500, 502, 503, 504) and attempt < max_attempts:
                    retry_after = int(resp.headers.get("Retry-After", delay))
                    await asyncio.sleep(retry_after)
                    delay *= 2
                    continue
                try:
                    body = resp.json()
                    err = body.get("detail") or body.get("title") or resp.text
                except Exception:
                    err = resp.text
                logger.error("[Twitter] API error %d: %s", status, err)
                return {"success": False, "error": f"Twitter API error {status}: {err}"}
            except httpx.TimeoutException:
                if attempt < max_attempts:
                    await asyncio.sleep(delay)
                    delay *= 2
                else:
                    return {"success": False, "error": "Request timed out"}
            except httpx.RequestError as exc:
                if attempt < max_attempts:
                    await asyncio.sleep(delay)
                    delay *= 2
                else:
                    return {"success": False, "error": f"Network error: {exc}"}
        return {"success": False, "error": "All retry attempts exhausted"}

    # ── OAuth 2.0 PKCE helpers ──────────────────────────────────────────────
    @staticmethod
    def create_pkce_state(username: str) -> tuple[str, str]:
        state = secrets.token_urlsafe(32)
        code_verifier = secrets.token_urlsafe(64)
        _pkce_states[state] = (username.lower(), code_verifier, time.time())
        now = time.time()
        expired = [s for s, (_, _, t) in _pkce_states.items() if now - t > _STATE_TTL]
        for s in expired:
            _pkce_states.pop(s, None)
        return state, code_verifier

    @staticmethod
    def _code_challenge(verifier: str) -> str:
        digest = hashlib.sha256(verifier.encode()).digest()
        return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()

    @staticmethod
    def get_auth_url(state: str, code_verifier: str) -> str:
        client_id = getattr(config, "TWITTER_CLIENT_ID", None)
        if not client_id:
            raise ValueError("TWITTER_CLIENT_ID is not configured.")
        redirect_uri = getattr(config, "TWITTER_REDIRECT_URI", None)
        if not redirect_uri:
            raise ValueError("TWITTER_REDIRECT_URI is not configured.")
        params = {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": " ".join(_TWITTER_SCOPES),
            "state": state,
            "code_challenge": TwitterService._code_challenge(code_verifier),
            "code_challenge_method": "S256",
        }
        return f"{_TWITTER_AUTH_URL}?{urlencode(params)}"

    @staticmethod
    def validate_pkce_state(state: str) -> Optional[tuple[str, str]]:
        entry = _pkce_states.pop(state, None)
        if not entry:
            return None
        username, code_verifier, created_at = entry
        if time.time() - created_at > _STATE_TTL:
            return None
        return username, code_verifier

    @staticmethod
    async def exchange_code(code: str, username: str, code_verifier: str) -> dict:
        client_id = getattr(config, "TWITTER_CLIENT_ID", None)
        client_secret = getattr(config, "TWITTER_CLIENT_SECRET", None)
        redirect_uri = getattr(config, "TWITTER_REDIRECT_URI", None)
        if not client_id:
            return {"success": False, "error": "Twitter OAuth not configured."}
        username = username.lower()
        try:
            auth = None
            if client_secret:
                auth = (client_id, client_secret)
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    _TWITTER_TOKEN_URL,
                    auth=auth,
                    data={
                        "grant_type": "authorization_code",
                        "code": code,
                        "redirect_uri": redirect_uri,
                        "code_verifier": code_verifier,
                        **({"client_id": client_id} if not client_secret else {}),
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
            if resp.status_code != 200:
                return {"success": False, "error": f"Token exchange failed: {resp.text}"}
            data = resp.json()
            access_token = data.get("access_token")
            refresh_token = data.get("refresh_token")
            expires_in = data.get("expires_in", 7200)
            if not access_token:
                return {"success": False, "error": "No access_token in Twitter response"}
            token_data = {
                "access_token": access_token,
                "expires_at": str(time.time() + expires_in),
                "token_type": data.get("token_type", "Bearer"),
            }
            if refresh_token:
                token_data["refresh_token"] = refresh_token
            await store_token(username, "twitter", token_data)
            logger.info("[Twitter] Token stored for user %s", username)
            return {"success": True}
        except Exception as exc:
            logger.error("[Twitter] exchange_code failed: %s", exc)
            return {"success": False, "error": str(exc)}

    @staticmethod
    async def refresh_token(username: str, refresh_token: str) -> Optional[str]:
        client_id = getattr(config, "TWITTER_CLIENT_ID", None)
        client_secret = getattr(config, "TWITTER_CLIENT_SECRET", None)
        if not client_id:
            return None
        username = username.lower()
        try:
            auth = (client_id, client_secret) if client_secret else None
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    _TWITTER_TOKEN_URL,
                    auth=auth,
                    data={
                        "grant_type": "refresh_token",
                        "refresh_token": refresh_token,
                        **({"client_id": client_id} if not client_secret else {}),
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
            if resp.status_code == 200:
                data = resp.json()
                new_token = data.get("access_token")
                expires_in = data.get("expires_in", 7200)
                new_refresh = data.get("refresh_token", refresh_token)
                if new_token:
                    await store_token(username, "twitter", {
                        "access_token": new_token,
                        "refresh_token": new_refresh,
                        "expires_at": str(time.time() + expires_in),
                    })
                    logger.info("[Twitter] Token refreshed for user %s", username)
                    return new_token
        except Exception as exc:
            logger.warning("[Twitter] Token refresh failed: %s", exc)
        return None