import json
import time
from typing import Any

from redis.asyncio import Redis

from app.lib.settings import settings

BLOCK_MAX = 5
SOCKET_TIMEOUT = 10

_client: Redis | None = None


def kv() -> Redis:
    global _client
    if _client is None:
        _client = Redis.from_url(settings.redis_url, decode_responses=True, socket_timeout=SOCKET_TIMEOUT)
    return _client


async def hit(key: str, limit: int, window: int) -> bool:
    n = await kv().incr(key)
    if n == 1:
        await kv().expire(key, window)
    return n <= limit


async def get_json(key: str, default: Any = None) -> Any:
    raw = await kv().get(key)
    return json.loads(raw) if raw else default


async def set_json(key: str, value: Any, ttl: int | None = None) -> None:
    await kv().set(key, json.dumps(value, default=str), ex=ttl)


async def beat(name: str, ttl: int = 30) -> None:
    await kv().set(f"beat:{name}", int(time.time()), ex=ttl)


async def alive(name: str) -> bool:
    return bool(await kv().exists(f"beat:{name}"))
