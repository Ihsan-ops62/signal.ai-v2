from fastapi import APIRouter, Depends, HTTPException
from api.dependencies.auth import get_current_active_user, User
from agents.social.linkedin_agent import LinkedInAgent
from agents.social.facebook_agent import FacebookAgent
from agents.social.twitter_agent import TwitterAgent

router = APIRouter()

@router.post("/linkedin/post")
async def linkedin_post(content: str, current_user: User = Depends(get_current_active_user)):
    result = await LinkedInAgent.post(content, username=current_user.username)
    if not result.get("success"):
        raise HTTPException(400, result.get("error"))
    return result

@router.post("/facebook/post")
async def facebook_post(content: str, current_user: User = Depends(get_current_active_user)):
    result = await FacebookAgent.post(content, username=current_user.username)
    if not result.get("success"):
        raise HTTPException(400, result.get("error"))
    return result

@router.post("/twitter/post")
async def twitter_post(content: str, current_user: User = Depends(get_current_active_user)):
    result = await TwitterAgent.post(content, username=current_user.username)
    if not result.get("success"):
        raise HTTPException(400, result.get("error"))
    return result