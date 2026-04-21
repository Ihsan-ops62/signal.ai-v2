"""
services/facebook_service.py
────────────────────────────
Facebook Graph API helper.
"""

import asyncio
import logging
import time
import httpx

from config import config
from database.mongodb_client import MongoDB

logger = logging.getLogger(__name__)

# Per‑user rate limiting for Facebook
async def _check_rate_limit(username: str, platform: str = "facebook") -> bool:
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
    if now - doc.get("last_reset", 0) > 60:
        await coll.update_one({"_id": doc["_id"]}, {"$set": {"count": 0, "last_reset": now}})
        return True
    if doc.get("count", 0) >= 1:
        logger.info("Rate limit hit for user %s on Facebook", username)
        return False
    await coll.update_one({"_id": doc["_id"]}, {"$inc": {"count": 1}, "$set": {"last_post_time": now}})
    return True


class FacebookService:
    _GRAPH_VERSION = "v20.0"

    @staticmethod
    async def create_post(
        content: str,
        access_token: str = None,
        page_id: str = None,
        username: str = None,
    ) -> dict:
        # ── EMPTY CONTENT VALIDATION ──────────────────────────────────────
        if not content or not content.strip():
            return {"success": False, "error": "Post content cannot be empty."}

        token = access_token
        pid   = page_id

        if username and (not token or not pid):
            try:
                from services.oauth_service import load_token
                record = await load_token(username.lower(), "facebook")
                if record:
                    if not token:
                        token = record.get("access_token")
                    if not pid:
                        pid = record.get("page_id")
            except Exception as exc:
                logger.warning("Could not load Facebook token for %s: %s", username, exc)

        if not token:
            token = getattr(config, "FACEBOOK_PAGE_ACCESS_TOKEN", None)
        if not pid:
            pid = getattr(config, "FACEBOOK_PAGE_ID", None)

        if not token:
            return {
                "success": False,
                "error": (
                    "No Facebook access token available. "
                    "Connect your Facebook account via Settings → Connected Accounts, "
                    "or provide a token manually."
                ),
            }
        if not pid:
            return {
                "success": False,
                "error": (
                    "No Facebook Page ID available. "
                    "Ensure your Facebook account is connected and a page_id is stored."
                ),
            }

        if username:
            allowed = await _check_rate_limit(username, "facebook")
            if not allowed:
                return {
                    "success": False,
                    "error": "Rate limit: Only one Facebook post per minute allowed. Please wait."
                }

        result = await FacebookService._post_with_retry(pid, token, content)

        if result["success"]:
            result["platform"] = "facebook"

        return result

    @staticmethod
    async def _post_with_retry(
        page_id: str,
        access_token: str,
        content: str,
        max_attempts: int = 3,
    ) -> dict:
        url   = f"https://graph.facebook.com/{FacebookService._GRAPH_VERSION}/{page_id}/feed"
        delay = 2.0
        payload = {
            "message":      content,
            "access_token": access_token,
        }

        for attempt in range(1, max_attempts + 1):
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.post(url, data=payload)
                status = resp.status_code
                logger.debug("Facebook POST attempt %d → HTTP %d", attempt, status)

                if status == 200:
                    post_id = resp.json().get("id", "unknown")
                    logger.info("Facebook post created: %s", post_id)
                    return {"success": True, "post_id": post_id}

                if status in (429, 500, 502, 503, 504) and attempt < max_attempts:
                    retry_after = int(resp.headers.get("Retry-After", delay))
                    logger.warning(
                        "Facebook %d on attempt %d/%d – retrying in %ds",
                        status, attempt, max_attempts, retry_after,
                    )
                    await asyncio.sleep(retry_after)
                    delay *= 2
                    continue

                error_msg = resp.text
                try:
                    error_msg = resp.json().get("error", {}).get("message", error_msg)
                except Exception:
                    pass
                logger.error("Facebook API error %d: %s", status, error_msg)
                return {"success": False, "error": f"Facebook API error {status}: {error_msg}"}

            except httpx.RequestError as exc:
                logger.exception("Facebook request error on attempt %d: %s", attempt, exc)
                if attempt < max_attempts:
                    await asyncio.sleep(delay)
                    delay *= 2
                    continue
                return {"success": False, "error": f"Network error: {exc}"}

        return {
            "success": False,
            "error":   f"Failed to post to Facebook after {max_attempts} attempts",
        }

    @staticmethod
    async def get_page_info(page_id: str, access_token: str) -> dict:
        url    = f"https://graph.facebook.com/{FacebookService._GRAPH_VERSION}/{page_id}"
        params = {
            "fields":       "id,name,about,picture",
            "access_token": access_token,
        }
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(url, params=params)
            if resp.status_code == 200:
                return {"success": True, "data": resp.json()}
            try:
                err = resp.json().get("error", {}).get("message", resp.text)
            except Exception:
                err = resp.text
            return {"success": False, "error": err}
        except Exception as exc:
            return {"success": False, "error": str(exc)}