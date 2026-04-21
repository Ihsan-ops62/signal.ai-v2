import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends

from api.schemas.request import SocialPostRequest, SocialPostResponse, PostResultSchema, OAuthCallbackRequest
from api.dependencies.auth import get_current_user, get_optional_user
from api.dependencies.rate_limit import check_rate_limit
from services.social.linkedin import LinkedInService
from services.social.twitter import TwitterService
from services.social.facebook import FacebookService
from services.oauth.oauth_service import get_oauth_service
from infrastructure.database.mongodb import MongoDB
from infrastructure.messaging.kafka import get_kafka_producer
from infrastructure.monitoring.metrics import MetricsCollector, MetricsContext
from core.security import generate_api_key

logger = logging.getLogger(__name__)

router = APIRouter()

# Service instances (no initialize/close needed as they are stateless in current impl)
linkedin_service = LinkedInService()
twitter_service = TwitterService()
facebook_service = FacebookService()


@router.post("/post", response_model=SocialPostResponse)
async def post_to_social(
    request: SocialPostRequest,
    current_user = Depends(get_current_user),
    _: None = Depends(check_rate_limit)
):
    """Post content to social media platforms."""
    try:
        with MetricsContext("agent_execution", agent="social", service="social"):
            results = []
            user_id = current_user.sub
            
            for platform in request.platforms:
                try:
                    if platform == "linkedin":
                        result = await linkedin_service.create_post(
                            content=request.content,
                            username=user_id
                        )
                    elif platform == "twitter":
                        result = await twitter_service.create_post(
                            content=request.content,
                            username=user_id
                        )
                    elif platform == "facebook":
                        result = await facebook_service.create_post(
                            content=request.content,
                            username=user_id
                        )
                    else:
                        continue
                    
                    # Standardize result format
                    post_result = {
                        "platform": platform,
                        "post_id": result.get("post_id") or result.get("tweet_id") or "",
                        "url": result.get("url", ""),
                        "status": "published" if result.get("success") else "failed",
                        "error": result.get("error")
                    }
                    results.append(PostResultSchema(**post_result))
                    
                    # Record metrics
                    MetricsCollector.record_social_post(
                        platform,
                        post_result["status"],
                        0
                    )
                    
                    # Store in MongoDB
                    mongodb = MongoDB.get_collection("posts")
                    post_data = {
                        "user_id": user_id,
                        "platform": platform,
                        "content": request.content,
                        "platform_post_id": post_result["post_id"],
                        "url": post_result["url"],
                        "status": post_result["status"],
                        "error": post_result["error"],
                        "created_at": datetime.utcnow()
                    }
                    await mongodb.insert_one(post_data)
                    
                    # Publish Kafka event (if producer available)
                    try:
                        producer = await get_kafka_producer()
                        if post_result["status"] == "published":
                            await producer.publish_post_published(post_data)
                        else:
                            await producer.publish_post_failed({
                                "post_id": post_result["post_id"],
                                "platform": platform,
                                "error": post_result["error"]
                            })
                    except Exception as kafka_err:
                        logger.warning(f"Kafka publish failed: {kafka_err}")
                
                except Exception as e:
                    logger.error(f"Failed to post to {platform}: {str(e)}")
                    results.append(PostResultSchema(
                        platform=platform,
                        post_id="",
                        url="",
                        status="failed",
                        error=str(e)
                    ))
            
            return SocialPostResponse(
                results=results,
                timestamp=datetime.utcnow()
            )
    
    except Exception as e:
        logger.error(f"Social posting failed: {str(e)}")
        MetricsCollector.record_error("SocialError", "post")
        raise HTTPException(status_code=500, detail="Social posting failed")


@router.get("/auth/linkedin")
async def linkedin_auth(current_user = Depends(get_current_user)):
    """Get LinkedIn OAuth URL."""
    try:
        oauth_service = await get_oauth_service()
        state = generate_api_key("state")
        
        # Store state in MongoDB
        await MongoDB.get_collection("oauth_states").insert_one({
            "state": state,
            "user_id": current_user.sub,
            "platform": "linkedin",
            "created_at": datetime.utcnow()
        })
        
        auth_url = oauth_service.get_linkedin_auth_url(state)
        return {"url": auth_url}
    except Exception as e:
        logger.error(f"LinkedIn auth failed: {str(e)}")
        raise HTTPException(status_code=500, detail="Auth failed")


@router.get("/auth/facebook")
async def facebook_auth(current_user = Depends(get_current_user)):
    """Get Facebook OAuth URL."""
    try:
        # Facebook OAuth not fully implemented in oauth_service yet
        raise HTTPException(status_code=501, detail="Facebook OAuth not yet implemented")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Facebook auth failed: {str(e)}")
        raise HTTPException(status_code=500, detail="Auth failed")


@router.post("/auth/callback")
async def oauth_callback(
    request: OAuthCallbackRequest,
    current_user = Depends(get_optional_user)
):
    """Handle OAuth callback."""
    try:
        states_coll = MongoDB.get_collection("oauth_states")
        
        # Validate state
        state_record = await states_coll.find_one({"state": request.state})
        if not state_record:
            raise HTTPException(status_code=400, detail="Invalid state")
        
        user_id = state_record["user_id"]
        platform = state_record["platform"]
        
        oauth_service = await get_oauth_service()
        
        if platform == "linkedin":
            result = await oauth_service.exchange_linkedin_code(request.code, user_id)
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported platform: {platform}")
        
        if not result.get("success"):
            raise HTTPException(status_code=400, detail=result.get("error", "OAuth exchange failed"))
        
        # Update user status
        await MongoDB.get_collection("users").update_one(
            {"_id": user_id},
            {"$set": {f"{platform}_connected": True}}
        )
        
        # Delete state
        await states_coll.delete_one({"state": request.state})
        
        logger.info(f"OAuth callback successful for {platform}: {user_id}")
        return {"status": "success", "platform": platform}
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"OAuth callback failed: {str(e)}")
        raise HTTPException(status_code=500, detail="Callback failed")
    
@router.get("/user/connections")
async def get_user_connections(current_user = Depends(get_current_user)):
    """Get social media connection status for current user."""
    try:
        from services.oauth.oauth_service import load_token
        import time

        async def get_status(platform):
            token_data = await load_token(current_user.sub, platform)
            if not token_data:
                return {"connected": False, "valid": False}
            exp = token_data.get("expires_at")
            valid = float(exp) > time.time() if exp else True
            return {"connected": True, "valid": valid}

        return {
            "linkedin": await get_status("linkedin"),
            "facebook": await get_status("facebook"),
            "twitter": await get_status("twitter"),
        }
    except Exception as e:
        logger.error(f"Failed to get connections: {e}")
        raise HTTPException(status_code=500, detail="Failed to get connections")