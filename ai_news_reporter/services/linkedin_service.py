import asyncio
import logging
import time
import httpx

from config import config

logger = logging.getLogger(__name__)

MIN_SECONDS_BETWEEN_POSTS: int = 60

_last_post_time: float = 0.0
_person_urn_cache: dict[str, str] = {}


class LinkedInService:
    """All LinkedIn API operations in one place."""

    # ── Authentication helpers ────────────────────────────────────────────────

    @staticmethod
    async def get_person_urn(access_token: str) -> str:
        """Return the authenticated user's person URN, cached per token.

        Caching avoids hitting ``/v2/userinfo`` on every single post.

        Raises:
            ValueError: If the token is invalid or the API response is malformed.
        """
        if access_token in _person_urn_cache:
            return _person_urn_cache[access_token]

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                "https://api.linkedin.com/v2/userinfo",
                headers={"Authorization": f"Bearer {access_token}"},
            )

        if resp.status_code == 200:
            sub = resp.json().get("sub")
            if not sub:
                raise ValueError("LinkedIn /userinfo response missing 'sub' field")
            urn = f"urn:li:person:{sub}"
            _person_urn_cache[access_token] = urn
            logger.info("Resolved person URN: %s", urn)
            return urn

        logger.error("Failed to get person URN: %s %s", resp.status_code, resp.text)
        raise ValueError(
            f"Unable to fetch LinkedIn person URN – "
            f"HTTP {resp.status_code}. Check your access token and scopes."
        )

    # ── Core posting logic ────────────────────────────────────────────────────

    @staticmethod
    async def create_post(content: str) -> dict:
        """Publish an organic text post to LinkedIn.

        Returns:
            ``{"success": True, "post_id": "<id>"}``  on success.
            ``{"success": False, "error": "<message>"}``  on failure.
        """
        global _last_post_time

        # Guard: token present
        token = getattr(config, "LINKEDIN_ACCESS_TOKEN", None)
        if not token:
            return {"success": False, "error": "LINKEDIN_ACCESS_TOKEN not set in environment"}

        # Guard: rate limit – wait if we posted too recently
        elapsed = time.time() - _last_post_time
        if elapsed < MIN_SECONDS_BETWEEN_POSTS:
            wait = MIN_SECONDS_BETWEEN_POSTS - elapsed
            logger.info("Rate-limit: waiting %.1f s before posting", wait)
            await asyncio.sleep(wait)

        # Resolve person URN
        try:
            person_urn = await LinkedInService.get_person_urn(token)
        except Exception as exc:
            return {"success": False, "error": f"Authentication failed: {exc}"}

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "LinkedIn-Version": "202504",
            "X-Restli-Protocol-Version": "2.0.0",
        }

        payload = {
            "author": person_urn,
            "commentary": content,
            "visibility": "PUBLIC",
            "distribution": {
                "feedDistribution": "MAIN_FEED",
                "targetEntities": [],
                "thirdPartyDistributionChannels": [],
            },
            "lifecycleState": "PUBLISHED",
            "isReshareDisabledByAuthor": False,
        }

        result = await LinkedInService._post_with_retry(headers, payload)

        if result["success"]:
            _last_post_time = time.time()

        return result

    # ── Internal helpers ──────────────────────────────────────────────────────

    @staticmethod
    async def _post_with_retry(
        headers: dict,
        payload: dict,
        max_attempts: int = 3,
    ) -> dict:
        """POST to the LinkedIn Posts API with exponential back-off.

        Retries on 429 (rate-limited) and 5xx (server errors).
        """
        url = "https://api.linkedin.com/rest/posts"
        delay = 2.0

        for attempt in range(1, max_attempts + 1):
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.post(url, headers=headers, json=payload)

                status = resp.status_code
                logger.debug("LinkedIn POST attempt %d → HTTP %d", attempt, status)

                if status == 201:
                    post_id = resp.headers.get("x-restli-id", "unknown")
                    logger.info("LinkedIn post created successfully: %s", post_id)
                    return {"success": True, "post_id": post_id}

                if status in (429, 500, 502, 503, 504):
                    retry_after = int(resp.headers.get("Retry-After", delay))
                    logger.warning(
                        "LinkedIn %d on attempt %d/%d – retrying in %ds",
                        status, attempt, max_attempts, retry_after,
                    )
                    if attempt < max_attempts:
                        await asyncio.sleep(retry_after)
                        delay *= 2
                        continue

                # Non-retryable error
                try:
                    err_json = resp.json()
                    message = err_json.get("message") or err_json.get("error", resp.text)
                except Exception:
                    message = resp.text

                logger.error("LinkedIn API error %d: %s", status, message)
                return {"success": False, "error": f"HTTP {status}: {message}"}

            except httpx.TimeoutException:
                logger.warning("LinkedIn request timed out (attempt %d/%d)", attempt, max_attempts)
                if attempt < max_attempts:
                    await asyncio.sleep(delay)
                    delay *= 2
                else:
                    return {"success": False, "error": "Request timed out after all retries"}

            except httpx.RequestError as exc:
                logger.error("Network error on attempt %d: %s", attempt, exc)
                if attempt < max_attempts:
                    await asyncio.sleep(delay)
                    delay *= 2
                else:
                    return {"success": False, "error": f"Network error: {exc}"}

        return {"success": False, "error": "All retry attempts exhausted"}