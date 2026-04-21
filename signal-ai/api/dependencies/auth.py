"""
Authentication dependencies for FastAPI.
"""
import logging
from typing import Optional

from fastapi import Depends, HTTPException, Header

from core.security import decode_token

logger = logging.getLogger(__name__)


class TokenData:
    def __init__(self, sub: str, scopes: list = None):
        self.sub = sub
        self.scopes = scopes or []


async def get_current_user(
    authorization: Optional[str] = Header(None)
) -> TokenData:
    """Get current user from JWT token (no DB dependency)."""
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing authorization header")
    try:
        scheme, credentials = authorization.split()
        if scheme.lower() != "bearer":
            raise HTTPException(status_code=401, detail="Invalid scheme")
        payload = decode_token(credentials)
        if not payload:
            raise HTTPException(status_code=401, detail="Invalid token")
        return TokenData(sub=payload.get("sub", "anonymous"))
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid authorization header")
    except Exception as e:
        logger.error(f"Auth error: {e}")
        raise HTTPException(status_code=401, detail="Authentication failed")


async def get_optional_user(
    authorization: Optional[str] = Header(None)
) -> Optional[TokenData]:
    if not authorization:
        return None
    try:
        return await get_current_user(authorization)
    except HTTPException:
        return None


async def require_admin(current_user: TokenData = Depends(get_current_user)) -> TokenData:
    if "admin" not in current_user.scopes:
        raise HTTPException(status_code=403, detail="Admin required")
    return current_user