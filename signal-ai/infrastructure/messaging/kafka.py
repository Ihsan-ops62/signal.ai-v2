import os
import json
import logging
from typing import Optional, Callable, Awaitable
from aiokafka import AIOKafkaProducer, AIOKafkaConsumer

logger = logging.getLogger(__name__)

KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")

class KafkaProducer:
    _producer: Optional[AIOKafkaProducer] = None

    @classmethod
    async def get_producer(cls) -> AIOKafkaProducer:
        if cls._producer is None:
            cls._producer = AIOKafkaProducer(
                bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
                value_serializer=lambda v: json.dumps(v).encode("utf-8")
            )
            await cls._producer.start()
            logger.info("Kafka producer started")
        return cls._producer

    @classmethod
    async def send(cls, topic: str, message: dict) -> None:
        producer = await cls.get_producer()
        await producer.send(topic, message)

    @classmethod
    async def close(cls):
        if cls._producer:
            await cls._producer.stop()
            cls._producer = None

class KafkaConsumer:
    @staticmethod
    async def consume(
        topic: str,
        group_id: str,
        handler: Callable[[dict], Awaitable[None]]
    ):
        consumer = AIOKafkaConsumer(
            topic,
            bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
            group_id=group_id,
            value_deserializer=lambda v: json.loads(v.decode("utf-8"))
        )
        await consumer.start()
        logger.info("Kafka consumer started for topic %s", topic)
        try:
            async for msg in consumer:
                await handler(msg.value)
        finally:
            await consumer.stop()