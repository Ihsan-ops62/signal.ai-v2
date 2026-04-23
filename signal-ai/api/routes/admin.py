from fastapi import APIRouter, Depends
from api.dependencies.auth import get_current_active_user, User
from infrastructure.database.mongodb import MongoDB

router = APIRouter()

@router.get("/stats")
async def get_stats(current_user: User = Depends(get_current_active_user)):
    queries_coll = MongoDB.get_collection("queries")
    posts_coll = MongoDB.get_collection("posts")
    query_count = await queries_coll.count_documents({"user_id": current_user.username})
    post_count = await posts_coll.count_documents({"user_id": current_user.username, "status": "success"})
    li_posts = await posts_coll.count_documents({"user_id": current_user.username, "platform": "linkedin", "status": "success"})
    fb_posts = await posts_coll.count_documents({"user_id": current_user.username, "platform": "facebook", "status": "success"})
    tw_posts = await posts_coll.count_documents({"user_id": current_user.username, "platform": "twitter", "status": "success"})
    return {
        "queries": query_count,
        "posts": post_count,
        "platforms": {"linkedin": li_posts, "facebook": fb_posts, "twitter": tw_posts},
    }

@router.get("/health")
async def health_check():
    return {"status": "ok", "graph_ready": True}