

import logging
from celery import Celery
from celery.schedules import crontab

from core.config import settings

logger = logging.getLogger(__name__)

config = settings

# Create Celery app
app = Celery(
    "signal_ai",
    broker=config.queue.celery_broker,
    backend=config.queue.celery_backend
)

# Configure Celery
app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=config.queue.task_timeout,
    task_soft_time_limit=config.queue.task_timeout - 60,
    result_expires=3600,  # 1 hour
    worker_prefetch_multiplier=4,
    worker_max_tasks_per_child=1000,
)

# Periodic tasks
app.conf.beat_schedule = {
    "fetch-trending-news": {
        "task": "services.queue.tasks.fetch_trending_news",
        "schedule": crontab(minute="*/15"),  # Every 15 minutes
    },
    "process-pending-posts": {
        "task": "services.queue.tasks.process_pending_posts",
        "schedule": crontab(minute="*/5"),  # Every 5 minutes
    },
    "health-check": {
        "task": "services.queue.tasks.health_check",
        "schedule": crontab(minute="*/10"),  # Every 10 minutes
    },
}


@app.task(bind=True)
def debug_task(self):
    """Debug task for testing."""
    logger.info(f"Celery task id: {self.request.id}")
    return "OK"


if __name__ == "__main__":
    app.start()
