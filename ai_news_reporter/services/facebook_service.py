import asyncio
import logging
import time
import httpx

from config import config

logger = logging.getLogger(__name__)

MIN_SECONDS_BETWEEN_POSTS: int = 60

_last_post_time: float = 0.0


class FacebookService:
    """All Facebook Graph API operations in one place."""

    @staticmethod
    async def create_post(content: str) -> dict:
        """Publish a text post to Facebook page.

        Returns:
            ``{"success": True, "post_id": "<id>"}``  on success.
            ``{"success": False, "error": "<message>"}``  on failure.
        """
        global _last_post_time

        # Guard: tokens and page ID present
        access_token = getattr(config, "FACEBOOK_PAGE_ACCESS_TOKEN", None)
        page_id = getattr(config, "FACEBOOK_PAGE_ID", None)

        if not access_token:
            return {"success": False, "error": "FACEBOOK_PAGE_ACCESS_TOKEN not set in environment"}

        if not page_id:
            return {"success": False, "error": "FACEBOOK_PAGE_ID not set in environment"}

        # Guard: rate limit – wait if we posted too recently
        elapsed = time.time() - _last_post_time
        if elapsed < MIN_SECONDS_BETWEEN_POSTS:
            wait = MIN_SECONDS_BETWEEN_POSTS - elapsed
            logger.info("Rate-limit: waiting %.1f s before posting to Facebook", wait)
            await asyncio.sleep(wait)

        result = await FacebookService._post_with_retry(page_id, access_token, content)

        if result["success"]:
            _last_post_time = time.time()

        return result

    @staticmethod
    async def _post_with_retry(
        page_id: str,
        access_token: str,
        content: str,
        max_attempts: int = 3,
    ) -> dict:
        """POST to the Facebook Graph API with exponential back-off.

        Retries on 429 (rate-limited) and 5xx (server errors).
        """
        url = f"https://graph.facebook.com/v20.0/{page_id}/feed"
        delay = 2.0

        payload = {
            "message": content,
            "access_token": access_token,
        }

        for attempt in range(1, max_attempts + 1):
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.post(url, data=payload)

                status = resp.status_code
                logger.debug("Facebook POST attempt %d → HTTP %d", attempt, status)

                if status == 200:
                    response_json = resp.json()
                    post_id = response_json.get("id", "unknown")
                    logger.info("Facebook post created successfully: %s", post_id)
                    return {"success": True, "post_id": post_id}

                if status in (429, 500, 502, 503, 504):
                    retry_after = int(resp.headers.get("Retry-After", delay))
                    logger.warning(
                        "Facebook %d on attempt %d/%d – retrying in %ds",
                        status, attempt, max_attempts, retry_after,
                    )
                    if attempt < max_attempts:
                        await asyncio.sleep(retry_after)
                        delay *= 2
                        continue

                # Non-retryable error
                error_msg = resp.text
                try:
                    error_data = resp.json()
                    error_msg = error_data.get("error", {}).get("message", error_msg)
                except Exception:
                    pass

                logger.error(
                    "Facebook API error %d: %s", status, error_msg
                )
                return {"success": False, "error": f"Facebook API error {status}: {error_msg}"}

            except httpx.RequestError as exc:
                logger.exception("Facebook request error on attempt %d: %s", attempt, exc)
                if attempt < max_attempts:
                    await asyncio.sleep(delay)
                    delay *= 2
                    continue
                return {"success": False, "error": f"Network error: {exc}"}
            except Exception as exc:
                logger.exception("Unexpected error posting to Facebook on attempt %d", attempt)
                return {"success": False, "error": f"Unexpected error: {exc}"}

        return {
            "success": False,
            "error": f"Failed to post to Facebook after {max_attempts} attempts",
        }

    @staticmethod
    async def get_page_info(page_id: str, access_token: str) -> dict:
        """Verify page access and retrieve page info.

        Returns:
            Page info or error details.
        """
        url = f"https://graph.facebook.com/v20.0/{page_id}"
        params = {
            "fields": "id,name,about,picture",
            "access_token": access_token,
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(url, params=params)

            if resp.status_code == 200:
                logger.info("Facebook page verified successfully")
                return {"success": True, "data": resp.json()}

            logger.error("Failed to verify Facebook page: %s %s", resp.status_code, resp.text)
            return {"success": False, "error": resp.text}

        except Exception as exc:
            logger.exception("Error verifying Facebook page: %s", exc)
            return {"success": False, "error": str(exc)}
