import json
import time
import logging
from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm
from api.dependencies.auth import (
    authenticate_user, create_access_token, get_current_active_user,
    get_password_hash, User, Token, ACCESS_TOKEN_EXPIRE_MINUTES, oauth2_scheme
)
from infrastructure.database.mongodb import MongoDB
from services.auth.oauth_service import (
    get_linkedin_auth_url, exchange_linkedin_code, create_oauth_state,
    validate_oauth_state, delete_token, load_token, store_token
)
from services.social.linkedin import LinkedInService
from services.social.twitter import TwitterService
import httpx
from core.config import config

logger = logging.getLogger(__name__)
router = APIRouter()

@router.post("/register")
async def register(username: str, password: str, email: str = None):
    coll = MongoDB.get_collection("users")
    # Check if username OR email already exists
    if await coll.find_one({"$or": [{"username": username.lower()}, {"email": email.lower() if email else ""}]}):
        raise HTTPException(status_code=400, detail="Username or Email already registered")
    
    hashed = get_password_hash(password)
    user_doc = {
        "username": username.lower(),
        "email": email.lower() if email else None,
        "hashed_password": hashed,
        "disabled": False,
        "created_at": time.time()
    }
    await coll.insert_one(user_doc)
    return {"message": "User created"}

@router.post("/token", response_model=Token)
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    user = await authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(401, "Incorrect credentials")
    token = create_access_token(data={"sub": user.username})
    return {"access_token": token, "token_type": "bearer"}

@router.post("/logout")
async def logout(current_user: User = Depends(get_current_active_user), token: str = Depends(oauth2_scheme)):
    coll = MongoDB.get_collection("token_blacklist")
    from jose import jwt
    from api.dependencies.auth import SECRET_KEY, ALGORITHM
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        exp = payload.get("exp", int(time.time()) + 3600)
    except Exception:
        exp = int(time.time()) + 3600
    await coll.update_one(
        {"token": token},
        {"$set": {"token": token, "username": current_user.username, "blacklisted_at": time.time(), "expires_at": exp}},
        upsert=True,
    )
    return {"message": "Logged out"}

@router.get("/me", response_model=User)
async def read_users_me(current_user: User = Depends(get_current_active_user)):
    return current_user

# LinkedIn OAuth
@router.get("/linkedin/connect")
async def linkedin_connect(current_user: User = Depends(get_current_active_user)):
    try:
        state = create_oauth_state(current_user.username)
        auth_url = get_linkedin_auth_url(state)
        return {"auth_url": auth_url}
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

@router.get("/linkedin/callback")
async def linkedin_callback(code: str, state: str):
    username = validate_oauth_state(state)
    if not username:
        return RedirectResponse(url=f"{config.FRONTEND_URL}?linkedin_error=invalid_state")
    result = await exchange_linkedin_code(code, username)
    if not result.get("success"):
        err = str(result.get("error", "unknown")).replace(" ", "_")[:60]
        return RedirectResponse(url=f"{config.FRONTEND_URL}?linkedin_error={err}")
    return RedirectResponse(url=f"{config.FRONTEND_URL}?linkedin_connected=true")

@router.delete("/linkedin/disconnect")
async def linkedin_disconnect(current_user: User = Depends(get_current_active_user)):
    await delete_token(current_user.username, "linkedin")
    return {"status": "disconnected", "platform": "linkedin"}

@router.post("/linkedin/manual-token")
async def linkedin_manual_token(access_token: str, current_user: User = Depends(get_current_active_user)):
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://api.linkedin.com/v2/userinfo",
                headers={"Authorization": f"Bearer {access_token}"},
            )
        if resp.status_code != 200:
            raise HTTPException(status_code=400, detail="Invalid LinkedIn access token")
        data = resp.json()
        sub = data.get("sub")
        if not sub:
            raise HTTPException(status_code=400, detail="Token lacks required 'sub' field")
        person_urn = f"urn:li:person:{sub}"
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Token validation failed: {str(e)}")

    expires_in = 60 * 24 * 3600
    token_data = {
        "access_token": access_token,
        "expires_at": str(time.time() + expires_in),
        "token_type": "Bearer",
        "person_urn": person_urn,
    }
    await store_token(current_user.username.lower(), "linkedin", token_data)
    return {"status": "connected", "platform": "linkedin"}

# Facebook manual token
@router.post("/facebook/manual-token")
async def facebook_manual_token(access_token: str, page_id: str, current_user: User = Depends(get_current_active_user)):
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"https://graph.facebook.com/v20.0/{page_id}",
                params={"access_token": access_token, "fields": "id,name"}
            )
        if resp.status_code != 200:
            raise HTTPException(status_code=400, detail="Invalid Facebook token or page ID")
        data = resp.json()
        if data.get("id") != page_id:
            raise HTTPException(status_code=400, detail="Page ID mismatch")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Validation failed: {str(e)}")

    token_data = {
        "access_token": access_token,
        "page_id": page_id,
        "expires_at": str(time.time() + 60 * 24 * 3600),
        "token_type": "Bearer",
    }
    await store_token(current_user.username.lower(), "facebook", token_data)
    return {"status": "connected", "platform": "facebook"}

@router.delete("/facebook/disconnect")
async def facebook_disconnect(current_user: User = Depends(get_current_active_user)):
    await delete_token(current_user.username, "facebook")
    return {"status": "disconnected"}

# Twitter OAuth
@router.get("/twitter/connect")
async def twitter_connect(current_user: User = Depends(get_current_active_user)):
    try:
        state, code_verifier = TwitterService.create_pkce_state(current_user.username)
        auth_url = TwitterService.get_auth_url(state, code_verifier)
        return {"auth_url": auth_url}
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

@router.get("/twitter/callback")
async def twitter_callback(code: str, state: str):
    validation_result = TwitterService.validate_pkce_state(state)
    if not validation_result:
        return RedirectResponse(url=f"{config.FRONTEND_URL}?twitter_error=invalid_state")
    username, code_verifier = validation_result
    result = await TwitterService.exchange_code(code, username, code_verifier)
    if not result.get("success"):
        err = str(result.get("error", "unknown")).replace(" ", "_")[:60]
        return RedirectResponse(url=f"{config.FRONTEND_URL}?twitter_error={err}")
    return RedirectResponse(url=f"{config.FRONTEND_URL}?twitter_connected=true")

@router.delete("/twitter/disconnect")
async def twitter_disconnect(current_user: User = Depends(get_current_active_user)):
    await delete_token(current_user.username, "twitter")
    return {"status": "disconnected", "platform": "twitter"}

@router.post("/twitter/manual-token")
async def twitter_manual_token(access_token: str, current_user: User = Depends(get_current_active_user)):
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://api.twitter.com/2/users/me",
                headers={"Authorization": f"Bearer {access_token}"}
            )
        if resp.status_code == 403:
            error_detail = resp.json().get("detail", "")
            if "oauth2" in error_detail.lower():
                raise HTTPException(
                    status_code=400,
                    detail="Token is invalid or missing required scopes."
                )
            else:
                raise HTTPException(status_code=400, detail=f"Twitter API error: {error_detail}")
        if resp.status_code != 200:
            raise HTTPException(status_code=400, detail=f"Invalid Twitter access token (HTTP {resp.status_code})")
        user_data = resp.json().get("data", {})
        user_id = user_data.get("id")
        if not user_id:
            raise HTTPException(status_code=400, detail="Token does not identify a Twitter user.")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Validation failed: {str(e)}")

    token_data = {
        "access_token": access_token,
        "expires_at": str(time.time() + 7200),
        "token_type": "Bearer",
        "twitter_user_id": user_id,
    }
    await store_token(current_user.username.lower(), "twitter", token_data)
    return {"status": "connected", "platform": "twitter", "user_id": user_id}

# User connections status
@router.get("/connections")
async def get_user_connections(current_user: User = Depends(get_current_active_user)):
    def _status(record):
        if not record:
            return {"connected": False, "valid": False}
        exp = record.get("expires_at")
        valid = True
        if exp:
            try:
                if isinstance(exp, str) and exp.startswith('gAAAAA'):
                    return {"connected": True, "valid": False, "error": "Token encryption mismatch"}
                exp_float = float(exp)
                valid = exp_float > time.time()
            except (ValueError, TypeError):
                valid = False
        return {"connected": True, "valid": valid}
    
    li = await load_token(current_user.username, "linkedin")
    fb = await load_token(current_user.username, "facebook")
    tw = await load_token(current_user.username, "twitter")
    return {
        "linkedin": _status(li),
        "facebook": _status(fb),
        "twitter": _status(tw),
    }