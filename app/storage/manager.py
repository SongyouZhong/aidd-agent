"""Hybrid storage manager — Redis hot cache + SeaweedFS cold archive.

Implements the read/write strategy described in backend design doc §3.3:
    - WRITE: append the new message to Redis (hot ring buffer) AND to
      SeaweedFS ``messages.jsonl`` (cold archive).
    - READ : fast path = Redis. On miss, rebuild from SeaweedFS and refill
      the cache.

This module is intentionally message-shape-agnostic: messages are arbitrary
JSON-serialisable dicts (typically ``{"role", "content", "ts", ...}``).
"""

from __future__ import annotations

import json
from typing import Any

from app.storage.redis_client import get_redis
from app.storage.s3 import messages_key, s3_storage

# Keep at most this many recent messages hot in Redis.
HOT_BUFFER_SIZE = 200
# Auto-evict the cache after 24h of inactivity (refreshed on every access).
HOT_BUFFER_TTL_SECONDS = 24 * 3600


def _cache_key(session_id: str) -> str:
    return f"session:{session_id}:messages"


async def append_message(session_id: str, message: dict[str, Any]) -> None:
    """Append a message to both Redis (hot) and SeaweedFS (cold)."""
    redis = await get_redis()
    key = _cache_key(session_id)
    payload = json.dumps(message, ensure_ascii=False)

    pipe = redis.pipeline()
    pipe.rpush(key, payload)
    pipe.ltrim(key, -HOT_BUFFER_SIZE, -1)
    pipe.expire(key, HOT_BUFFER_TTL_SECONDS)
    await pipe.execute()

    await s3_storage.append_jsonl(messages_key(session_id), message)


async def load_messages(session_id: str, limit: int | None = None) -> list[dict[str, Any]]:
    """Return messages for a session.

    Hits Redis first; on a miss, rebuilds the cache from SeaweedFS.
    """
    redis = await get_redis()
    key = _cache_key(session_id)

    cached = await redis.lrange(key, 0, -1)
    if cached:
        await redis.expire(key, HOT_BUFFER_TTL_SECONDS)
        messages = [json.loads(s) for s in cached]
    else:
        messages = await s3_storage.read_jsonl(messages_key(session_id))
        if messages:
            tail = messages[-HOT_BUFFER_SIZE:]
            pipe = redis.pipeline()
            pipe.delete(key)
            pipe.rpush(key, *(json.dumps(m, ensure_ascii=False) for m in tail))
            pipe.expire(key, HOT_BUFFER_TTL_SECONDS)
            await pipe.execute()

    if limit is not None:
        return messages[-limit:]
    return messages


async def drop_session_cache(session_id: str) -> None:
    redis = await get_redis()
    await redis.delete(_cache_key(session_id))
