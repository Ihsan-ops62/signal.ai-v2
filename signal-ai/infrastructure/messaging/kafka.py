
import json
import logging
from typing import Callable, Any, Optional
from enum import Enum

from aiokafka import AIOKafkaProducer, AIOKafkaConsumer
from aiokafka.errors import KafkaError

from core.config import settings
from core.exceptions import ExternalServiceError

logger = logging.getLogger(__name__)


class EventType(str, Enum):
    """Kafka event types."""
    # Article events
    ARTICLE_DISCOVERED = "article.discovered"
    ARTICLE_PROCESSED = "article.processed"
    ARTICLE_SUMMARIZED = "article.summarized"
    
    # Posting events
    POST_CREATED = "post.created"
    POST_SCHEDULED = "post.scheduled"
    POST_PUBLISHED = "post.published"
    POST_FAILED = "post.failed"
    
    # User events
    USER_REGISTERED = "user.registered"
    USER_DELETED = "user.deleted"
    
    # System events
    HEALTH_CHECK = "system.health_check"
    ERROR = "system.error"


class KafkaProducerService:
    """Kafka producer for publishing events."""
    
    def __init__(self):
        self.producer: AIOKafkaProducer | None = None
    
    async def connect(self) -> None:
        """Initialize Kafka producer."""
        try:
            # Default to localhost; override with env if set
            bootstrap_servers = getattr(settings, 'KAFKA_BOOTSTRAP_SERVERS', 'localhost:9092')
            
            self.producer = AIOKafkaProducer(
                bootstrap_servers=bootstrap_servers,
                value_serializer=self._serialize_value,
                acks="all",
                retries=3,
                retry_backoff_ms=100,
            )
            await self.producer.start()
            logger.info("Kafka producer connected")
        except Exception as e:
            logger.warning(f"Failed to connect Kafka producer (optional): {str(e)}")
            self.producer = None  # Continue without Kafka
    
    async def disconnect(self) -> None:
        """Disconnect Kafka producer."""
        if self.producer:
            await self.producer.stop()
            logger.info("Kafka producer disconnected")
    
    def _serialize_value(self, value: Any) -> bytes:
        """Serialize message value."""
        if isinstance(value, dict):
            return json.dumps(value).encode('utf-8')
        elif isinstance(value, str):
            return value.encode('utf-8')
        return str(value).encode('utf-8')
    
    async def publish(
        self,
        topic: str,
        event_type: str,
        data: dict[str, Any],
        key: str | None = None
    ) -> None:
        """
        Publish event to Kafka.
        
        Args:
            topic: Topic name
            event_type: Event type
            data: Event data
            key: Message key for partitioning
        """
        if not self.producer:
            logger.debug(f"Kafka not available, skipping publish of {event_type}")
            return
        
        try:
            message = {
                "event_type": event_type,
                "data": data
            }
            
            await self.producer.send_and_wait(
                topic,
                value=message,
                key=key.encode('utf-8') if key else None
            )
            
            logger.debug(f"Published {event_type} to {topic}")
        except KafkaError as e:
            logger.error(f"Failed to publish event: {str(e)}")
            # Don't raise; Kafka is optional
    
    async def publish_article_discovered(self, article: dict[str, Any]) -> None:
        """Publish article discovered event."""
        await self.publish(
            "articles",
            EventType.ARTICLE_DISCOVERED,
            article,
            key=article.get("source_id")
        )
    
    async def publish_post_published(self, post: dict[str, Any]) -> None:
        """Publish post published event."""
        await self.publish(
            "posts",
            EventType.POST_PUBLISHED,
            post,
            key=str(post.get("user_id"))
        )
    
    async def publish_post_failed(self, error_data: dict[str, Any]) -> None:
        """Publish post failed event."""
        await self.publish(
            "posts",
            EventType.POST_FAILED,
            error_data
        )


class KafkaConsumerService:
    """Kafka consumer for subscribing to events."""
    
    def __init__(self, group_id: str):
        self.group_id = group_id
        self.consumer: AIOKafkaConsumer | None = None
        self.handlers: dict[str, list[Callable]] = {}
    
    async def connect(self, topics: list[str]) -> None:
        """Initialize Kafka consumer."""
        try:
            bootstrap_servers = getattr(settings, 'KAFKA_BOOTSTRAP_SERVERS', 'localhost:9092')
            
            self.consumer = AIOKafkaConsumer(
                *topics,
                bootstrap_servers=bootstrap_servers,
                group_id=self.group_id,
                value_deserializer=self._deserialize_value,
                auto_offset_reset='earliest',
                enable_auto_commit=True,
            )
            await self.consumer.start()
            logger.info(f"Kafka consumer connected to {self.group_id}")
        except Exception as e:
            logger.error(f"Failed to connect Kafka consumer: {str(e)}")
            raise ExternalServiceError("Kafka", f"Consumer connection failed: {str(e)}")
    
    async def disconnect(self) -> None:
        """Disconnect Kafka consumer."""
        if self.consumer:
            await self.consumer.stop()
            logger.info("Kafka consumer disconnected")
    
    def _deserialize_value(self, value: bytes) -> dict[str, Any]:
        """Deserialize message value."""
        try:
            return json.loads(value.decode('utf-8'))
        except json.JSONDecodeError:
            return {"raw": value.decode('utf-8')}
    
    def register_handler(
        self,
        event_type: str,
        handler: Callable[[dict[str, Any]], Any]
    ) -> None:
        """Register event handler."""
        if event_type not in self.handlers:
            self.handlers[event_type] = []
        self.handlers[event_type].append(handler)
    
    async def start_consuming(self) -> None:
        """Start consuming messages."""
        if not self.consumer:
            raise ExternalServiceError("Kafka", "Consumer not connected")
        
        try:
            async for message in self.consumer:
                try:
                    value = message.value
                    event_type = value.get("event_type")
                    data = value.get("data")
                    
                    # Call registered handlers
                    if event_type in self.handlers:
                        for handler in self.handlers[event_type]:
                            await handler(data)
                    
                    logger.debug(f"Processed event: {event_type}")
                except Exception as e:
                    logger.error(f"Error processing message: {str(e)}")
        except Exception as e:
            logger.error(f"Consumer error: {str(e)}")


# Global instances
_producer: KafkaProducerService | None = None
_consumers: dict[str, KafkaConsumerService] = {}


async def get_kafka_producer() -> KafkaProducerService:
    """Get Kafka producer instance."""
    global _producer
    if _producer is None:
        _producer = KafkaProducerService()
        await _producer.connect()
    return _producer


async def get_kafka_consumer(group_id: str, topics: list[str]) -> KafkaConsumerService:
    """Get Kafka consumer instance."""
    global _consumers
    
    if group_id not in _consumers:
        consumer = KafkaConsumerService(group_id)
        await consumer.connect(topics)
        _consumers[group_id] = consumer
    
    return _consumers[group_id]