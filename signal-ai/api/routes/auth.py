"""
Authentication routes for Signal AI.
"""
import logging
import time
from datetime import datetime

from fastapi import APIRouter, HTTPException, Depends, Header

from api.schemas.request import RegisterRequest, LoginRequest, TokenResponse
from api.dependencies.auth import get_current_user
from api.dependencies.rate_limit import check_rate_limit
from core.security import hash_password, verify_password, create_tokens, decode_token
from infrastructure.database.mongodb import MongoDB
from services.oauth.oauth_service import store_token, delete_token

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/register", response_model=TokenResponse)
async def register(
    request: RegisterRequest,
    _: None = Depends(check_rate_limit)
):
    try:
        users_coll = MongoDB.get_collection("users")
        
        existing = await users_coll.find_one({"email": request.email})
        if existing:
            raise HTTPException(status_code=409, detail="User already exists")
        
        user_data = {
            "email": request.email,
            "name": request.name,
            "password_hash": hash_password(request.password),
            "created_at": datetime.utcnow(),
            "linkedin_connected": False,
            "twitter_connected": False,
            "facebook_connected": False,
        }
        
        result = await users_coll.insert_one(user_data)
        user_id = str(result.inserted_id)
        
        tokens = create_tokens(user_id)
        
        logger.info(f"User registered: {request.email}")
        return TokenResponse(**tokens)
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Registration failed: {str(e)}")
        raise HTTPException(status_code=500, detail="Registration failed")


@router.post("/login", response_model=TokenResponse)
async def login(
    request: LoginRequest,
    _: None = Depends(check_rate_limit)
):
    try:
        users_coll = MongoDB.get_collection("users")
        
        user = await users_coll.find_one({"email": request.email})
        if not user:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        
        if not verify_password(request.password, user.get("password_hash", "")):
            raise HTTPException(status_code=401, detail="Invalid credentials")
        
        user_id = str(user["_id"])
        tokens = create_tokens(user_id)
        
        logger.info(f"User logged in: {request.email}")
        return TokenResponse(**tokens)
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Login failed: {str(e)}")
        raise HTTPException(status_code=500, detail="Login failed")


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    authorization: str = Header(None),
    _: None = Depends(check_rate_limit)
):
    try:
        if not authorization:
            raise HTTPException(status_code=401, detail="Missing refresh token")
        
        scheme, credentials = authorization.split()
        if scheme.lower() != "bearer":
            raise HTTPException(status_code=401, detail="Invalid scheme")
        
        payload = decode_token(credentials)
        if not payload or payload.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="Invalid refresh token")
        
        user_id = payload.get("sub")
        tokens = create_tokens(user_id)
        
        logger.info(f"Token refreshed for user: {user_id}")
        return TokenResponse(**tokens)
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Token refresh failed: {str(e)}")
        raise HTTPException(status_code=401, detail="Token refresh failed")


@router.get("/me")
async def get_current_user_info(
    current_user = Depends(get_current_user)
):
    try:
        users_coll = MongoDB.get_collection("users")
        from bson import ObjectId
        user = await users_coll.find_one({"_id": ObjectId(current_user.sub)})
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        return {
            "id": current_user.sub,
            "email": user.get("email"),
            "name": user.get("name"),
            "linkedin_connected": user.get("linkedin_connected", False),
            "twitter_connected": user.get("twitter_connected", False),
            "facebook_connected": user.get("facebook_connected", False),
        }
    except Exception as e:
        logger.error(f"Failed to get user info: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get user info")


# ========== MANUAL TOKEN ENDPOINTS ==========

@router.post("/linkedin/manual-token")
async def store_linkedin_token(
    access_token: str,
    current_user = Depends(get_current_user)
):
    """Store a manually provided LinkedIn access token."""
    token_data = {
        "access_token": access_token,
        "expires_at": str(time.time() + 5184000),  # 60 days
        "token_type": "Bearer",
    }
    await store_token(current_user.sub, "linkedin", token_data)
    # Also update user's connection flag
    users_coll = MongoDB.get_collection("users")
    from bson import ObjectId
    await users_coll.update_one(
        {"_id": ObjectId(current_user.sub)},
        {"$set": {"linkedin_connected": True}}
    )
    return {"success": True}

@router.delete("/linkedin/disconnect")
async def disconnect_linkedin(current_user = Depends(get_current_user)):
    await delete_token(current_user.sub, "linkedin")
    users_coll = MongoDB.get_collection("users")
    from bson import ObjectId
    await users_coll.update_one(
        {"_id": ObjectId(current_user.sub)},
        {"$set": {"linkedin_connected": False}}
    )
    return {"success": True}


@router.post("/facebook/manual-token")
async def store_facebook_token(
    access_token: str,
    page_id: str,
    current_user = Depends(get_current_user)
):
    """Store a manually provided Facebook access token and page ID."""
    token_data = {
        "access_token": access_token,
        "page_id": page_id,
        "expires_at": str(time.time() + 5184000),
    }
    await store_token(current_user.sub, "facebook", token_data)
    users_coll = MongoDB.get_collection("users")
    from bson import ObjectId
    await users_coll.update_one(
        {"_id": ObjectId(current_user.sub)},
        {"$set": {"facebook_connected": True}}
    )
    return {"success": True}

@router.delete("/facebook/disconnect")
async def disconnect_facebook(current_user = Depends(get_current_user)):
    await delete_token(current_user.sub, "facebook")
    users_coll = MongoDB.get_collection("users")
    from bson import ObjectId
    await users_coll.update_one(
        {"_id": ObjectId(current_user.sub)},
        {"$set": {"facebook_connected": False}}
    )
    return {"success": True}


@router.post("/twitter/manual-token")
async def store_twitter_token(
    access_token: str,
    current_user = Depends(get_current_user)
):
    """Store a manually provided Twitter access token."""
    token_data = {
        "access_token": access_token,
        "expires_at": str(time.time() + 7200),  # 2 hours typical
    }
    await store_token(current_user.sub, "twitter", token_data)
    users_coll = MongoDB.get_collection("users")
    from bson import ObjectId
    await users_coll.update_one(
        {"_id": ObjectId(current_user.sub)},
        {"$set": {"twitter_connected": True}}
    )
    return {"success": True}

@router.delete("/twitter/disconnect")
async def disconnect_twitter(current_user = Depends(get_current_user)):
    await delete_token(current_user.sub, "twitter")
    users_coll = MongoDB.get_collection("users")
    from bson import ObjectId
    await users_coll.update_one(
        {"_id": ObjectId(current_user.sub)},
        {"$set": {"twitter_connected": False}}
    )
    return {"success": True}