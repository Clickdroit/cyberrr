"""
Redis Pub/Sub helper — publishes and subscribes to scan progress events.
Used to bridge Celery workers → FastAPI WebSocket handlers.
"""
import asyncio
import json
import os
from typing import AsyncGenerator, Callable

import redis.asyncio as aioredis

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")


def get_channel(scan_id: str) -> str:
    """Return the Redis channel name for a given scan."""
    return f"osint:scan:{scan_id}"


async def publish_event(scan_id: str, event: str, data: dict):
    """Publish a WebSocket event to the scan's Redis channel."""
    r = aioredis.from_url(REDIS_URL, decode_responses=True)
    try:
        payload = json.dumps({"event": event, "scan_id": scan_id, "data": data})
        await r.publish(get_channel(scan_id), payload)
    finally:
        await r.aclose()


def publish_event_sync(scan_id: str, event: str, data: dict):
    """
    Synchronous wrapper — used inside Celery workers which run
    in a non-async context.
    """
    import redis as sync_redis
    import os

    r = sync_redis.from_url(
        os.getenv("REDIS_URL", "redis://redis:6379/0"),
        decode_responses=True,
    )
    try:
        payload = json.dumps({"event": event, "scan_id": scan_id, "data": data})
        r.publish(get_channel(scan_id), payload)
    finally:
        r.close()


async def subscribe_to_scan(
    scan_id: str,
) -> AsyncGenerator[dict, None]:
    """
    Async generator that yields events published to a scan's channel.
    Used in the WebSocket handler to stream events to the browser.
    """
    r = aioredis.from_url(REDIS_URL, decode_responses=True)
    pubsub = r.pubsub()
    channel = get_channel(scan_id)

    await pubsub.subscribe(channel)

    try:
        async for message in pubsub.listen():
            if message["type"] == "message":
                try:
                    yield json.loads(message["data"])
                except json.JSONDecodeError:
                    continue
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.aclose()
        await r.aclose()
