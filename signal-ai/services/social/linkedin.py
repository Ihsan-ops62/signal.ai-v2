import asyncio
import logging
import time
import hashlib
import httpx
from typing import Optional
from services.auth.oauth_service import load_token, get_access_token
from infrastructure.database.mongodb import MongoDB

logger = logging.getLogger(__name__)

async def _check_rate_limit(username: str, platform: str = "linkedin") -> bool:
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
        logger.info("Rate limit hit for user %s on LinkedIn", username)
        return False
    await coll.update_one({"_id": doc["_id"]}, {"$inc": {"count": 1}, "$set": {"last_post_time": now}})
    return True

async def _is_duplicate_content(username: str, content: str) -> bool:
    if not username:
        return False
    coll = MongoDB.get_collection("posts")
    content_hash = hashlib.md5(content.encode()).hexdigest()
    one_hour_ago = time.time() - 3600
    doc = await coll.find_one({
        "user_id": username,
        "content_hash": content_hash,
        "created_at": {"$gt": one_hour_ago}
    })
    if doc:
        logger.info("Duplicate content detected for user %s", username)
        return True
    return False

class LinkedInService:
    _API_VERSION = "202603"  
    _POSTS_URL   = "https://api.linkedin.com/rest/posts"

    @staticmethod
    async def _resolve_token(username: str) -> Optional[str]:
        if not username:
            return None
        username = username.lower()
        try:
            token = await get_access_token(username, "linkedin")
            return token
        except Exception as exc:
            logger.error("[LinkedIn] Token resolution error: %s", exc)
            return None

    @staticmethod
    async def get_person_urn(access_token: str, username: Optional[str] = None) -> str:
        if username:
            username = username.lower()
            try:
                record = await load_token(username, "linkedin")
                if record and record.get("person_urn"):
                    return record["person_urn"]
            except Exception:
                pass

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                "https://api.linkedin.com/v2/userinfo",
                headers={"Authorization": f"Bearer {access_token}"},
            )
        if resp.status_code == 200:
            sub = resp.json().get("sub")
            if not sub:
                raise ValueError("LinkedIn /userinfo response missing 'sub' field")
            return f"urn:li:person:{sub}"
        raise ValueError(f"Unable to fetch LinkedIn person URN — HTTP {resp.status_code}")

    @staticmethod
    async def create_post(content: str, access_token: Optional[str] = None,
                          username: Optional[str] = None) -> dict:
        if not content or not content.strip():
            return {"success": False, "error": "Post content cannot be empty."}

        token = None
        if access_token:
            token = access_token
        elif username:
            token = await LinkedInService._resolve_token(username)

        if not token:
            return {
                "success": False,
                "error": "No LinkedIn access token found for this user."
            }

        if username and await _is_duplicate_content(username, content):
            return {
                "success": False,
                "error": "Duplicate post: You already published this exact content recently."
            }

        if username:
            allowed = await _check_rate_limit(username, "linkedin")
            if not allowed:
                return {
                    "success": False,
                    "error": "Rate limit: Only one LinkedIn post per minute allowed."
                }

        try:
            person_urn = await LinkedInService.get_person_urn(token, username)
        except Exception as exc:
            return {"success": False, "error": f"Authentication failed: {exc}"}

        headers = {
            "Authorization":             f"Bearer {token}",
            "Content-Type":              "application/json",
            "LinkedIn-Version":          LinkedInService._API_VERSION,
            "X-Restli-Protocol-Version": "2.0.0",
        }
        payload = {
            "author":      person_urn,
            "commentary":  content,
            "visibility":  "PUBLIC",
            "distribution": {
                "feedDistribution": "MAIN_FEED",
                "targetEntities": [],
                "thirdPartyDistributionChannels": [],
            },
            "lifecycleState":            "PUBLISHED",
            "isReshareDisabledByAuthor": False,
        }

        result = await LinkedInService._post_with_retry(headers, payload)
        if result["success"]:
            result["platform"] = "linkedin"
        return result

    @staticmethod
    async def delete_post(post_id: str, access_token: Optional[str] = None,
                          username: Optional[str] = None) -> dict:
        token = None
        if access_token:
            token = access_token
        elif username:
            token = await LinkedInService._resolve_token(username)

        if not token:
            return {"success": False, "error": "No LinkedIn access token available."}

        if not post_id.startswith("urn:"):
            post_id = f"urn:li:share:{post_id}"

        headers = {
            "Authorization":             f"Bearer {token}",
            "LinkedIn-Version":          LinkedInService._API_VERSION,
            "X-Restli-Protocol-Version": "2.0.0",
        }
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.delete(
                    f"{LinkedInService._POSTS_URL}/{post_id}",
                    headers=headers,
                )
            if resp.status_code in (200, 204):
                logger.info("LinkedIn post deleted: %s", post_id)
                return {"success": True, "post_id": post_id}
            try:
                err = resp.json().get("message", resp.text)
            except Exception:
                err = resp.text
            return {"success": False, "error": f"HTTP {resp.status_code}: {err}"}
        except Exception as exc:
            logger.error("delete_post failed: %s", exc)
            return {"success": False, "error": str(exc)}

    @staticmethod
    async def _post_with_retry(headers: dict, payload: dict, max_attempts: int = 3) -> dict:
        delay = 2.0
        for attempt in range(1, max_attempts + 1):
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.post(LinkedInService._POSTS_URL,
                                             headers=headers, json=payload)
                status = resp.status_code
                if status == 201:
                    post_id = resp.headers.get("x-restli-id", "unknown")
                    logger.info("LinkedIn post created: %s", post_id)
                    return {"success": True, "post_id": post_id}
                if status in (429, 500, 502, 503, 504) and attempt < max_attempts:
                    retry_after = int(resp.headers.get("Retry-After", delay))
                    await asyncio.sleep(retry_after)
                    delay *= 2
                    continue
                try:
                    message = resp.json().get("message") or resp.text
                except Exception:
                    message = resp.text
                return {"success": False, "error": f"HTTP {status}: {message}"}
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