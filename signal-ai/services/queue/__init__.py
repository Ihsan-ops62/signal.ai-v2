"""Queue and task services."""
from services.queue.celery_app import app as celery_app

__all__ = ["celery_app"]
