import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException, Header, Body

from infrastructure.database.mongodb import MongoDB
from infrastructure.messaging.kafka import get_kafka_producer
from infrastructure.monitoring.metrics import MetricsCollector

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/news-source")
async def news_source_webhook(
    payload: dict = Body(...),
    x_signature: str = Header(None)
):
    """Receive news updates from external source."""
    try:
        if not x_signature:
            # In production, verify signature
            pass
        
        article_id = await MongoDB.get_collection("articles").insert_one({
            **payload,
            "source": "webhook",
            "created_at": datetime.utcnow(),
            "quality_score": 75
        })
        
        try:
            producer = await get_kafka_producer()
            await producer.publish("articles", "article.discovered", payload)
        except Exception as e:
            logger.warning(f"Kafka publish failed: {e}")
        
        MetricsCollector.record_news_processing("webhook")
        
        logger.info(f"Received article via webhook: {article_id}")
        return {"status": "success", "id": str(article_id.inserted_id)}
    
    except Exception as e:
        logger.error(f"Webhook processing failed: {str(e)}")
        raise HTTPException(status_code=500, detail="Webhook processing failed")


@router.post("/social-events")
async def social_events_webhook(
    payload: dict = Body(...),
    x_platform: str = Header(None)
):
    """Receive social media events."""
    try:
        if not x_platform:
            raise HTTPException(status_code=400, detail="Missing platform header")
        
        event_id = await MongoDB.get_collection("social_events").insert_one({
            "platform": x_platform,
            "event_type": payload.get("type"),
            "data": payload,
            "created_at": datetime.utcnow()
        })
        
        try:
            producer = await get_kafka_producer()
            await producer.publish("social_events", f"social.{payload.get('type')}", payload)
        except Exception as e:
            logger.warning(f"Kafka publish failed: {e}")
        
        logger.info(f"Received social event from {x_platform}: {event_id.inserted_id}")
        return {"status": "success", "id": str(event_id.inserted_id)}
    
    except Exception as e:
        logger.error(f"Social event webhook failed: {str(e)}")
        raise HTTPException(status_code=500, detail="Event processing failed")


@router.post("/errors")
async def error_webhook(payload: dict = Body(...)):
    """Receive error reports."""
    try:
        await MongoDB.get_collection("error_reports").insert_one({
            **payload,
            "received_at": datetime.utcnow()
        })
        
        MetricsCollector.record_error(payload.get("type", "Unknown"), "webhook")
        
        logger.warning(f"Error reported via webhook: {payload.get('type')}")
        return {"status": "received"}
    
    except Exception as e:
        logger.error(f"Error webhook failed: {str(e)}")
        raise HTTPException(status_code=500, detail="Error logging failed")