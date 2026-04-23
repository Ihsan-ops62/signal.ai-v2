import asyncio
import os
import time
from typing import Optional
from fastapi import Depends, HTTPException, status, WebSocket
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel
from infrastructure.database.mongodb import MongoDB
from core.security import get_password_hash, verify_password, create_access_token, decode_token
from core.exceptions import AuthenticationError
from core.config import config

SECRET_KEY = os.getenv("SECRET_KEY") or getattr(config, "SECRET_KEY", "change-me-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    username: Optional[str] = None

class User(BaseModel):
    username: str
    email: Optional[str] = None
    full_name: Optional[str] = None
    disabled: Optional[bool] = None

class UserInDB(User):
    hashed_password: str

async def get_user(username: str) -> Optional[UserInDB]:
    doc = await MongoDB.get_collection("users").find_one({"username": username})
    return UserInDB(**doc) if doc else None

async def authenticate_user(username: str, password: str) -> Optional[UserInDB]:
    user = await get_user(username)
    if not user or not verify_password(password, user.hashed_password):
        return None
    return user

async def _is_token_blacklisted(token: str) -> bool:
    coll = MongoDB.get_collection("token_blacklist")
    doc = await coll.find_one({"token": token})
    return doc is not None

async def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if await _is_token_blacklisted(token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been invalidated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = decode_token(token)
    if not payload:
        raise credentials_exception
    username: str = payload.get("sub")
    if username is None:
        raise credentials_exception
    user = await get_user(username)
    if user is None:
        raise credentials_exception
    return user

async def get_current_active_user(current_user: User = Depends(get_current_user)) -> User:
    if current_user.disabled:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user

async def get_current_user_ws(websocket: WebSocket, auth_timeout: float = 5.0) -> Optional[User]:
   
    try:
        # Set a receive timeout to prevent hanging indefinitely
        import asyncio
        try:
            data = await asyncio.wait_for(websocket.receive_json(), timeout=auth_timeout)
        except asyncio.TimeoutError:
            await websocket.close(code=1008, reason="Authentication timeout - no token received within 5 seconds")
            return None
        except Exception as e:
            # Client sent something that wasn't JSON (e.g., binary audio)
            await websocket.close(code=1008, reason="Invalid auth format - expected JSON with token")
            return None
        
        token = data.get("token")
        if not token:
            await websocket.close(code=1008, reason="Missing token in auth message")
            return None
        
        payload = decode_token(token)
        if not payload:
            await websocket.close(code=1008, reason="Invalid or expired token")
            return None
        
        username = payload.get("sub")
        if not username:
            await websocket.close(code=1008, reason="Invalid token payload")
            return None
        
        user = await get_user(username)
        if not user:
            await websocket.close(code=1008, reason="User not found")
            return None
        
        return user
    except Exception as e:
        await websocket.close(code=1008, reason=f"Authentication error: {str(e)[:100]}")
        return None