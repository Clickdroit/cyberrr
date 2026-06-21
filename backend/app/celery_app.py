"""
Celery application configuration.
Uses Redis as both broker and result backend.
"""
import os
from celery import Celery

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

celery_app = Celery(
    "osint_hub",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=[
        "app.workers.orchestrator",
    ],
)

celery_app.conf.update(
    # Serialization
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    # Timezone
    timezone="UTC",
    enable_utc=True,
    # Task settings
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    # Result expiry (24h)
    result_expires=86400,
    # Task time limits
    task_soft_time_limit=300,   # 5 min soft limit
    task_time_limit=600,        # 10 min hard limit
    # Queues
    task_default_queue="default",
    task_queues={
        "default": {"exchange": "default", "routing_key": "default"},
        "username_queue": {"exchange": "osint", "routing_key": "username"},
        "email_queue": {"exchange": "osint", "routing_key": "email"},
    },
)
