import json
from typing import Any

import msgspec
import socketio

from app.lib import log
from app.lib.kv import kv
from app.lib.settings import settings

STREAM = "rt:stream"
_mgr: socketio.AsyncRedisManager | None = None
_log = log.get("realtime")


def manager() -> socketio.AsyncRedisManager:
    global _mgr
    if _mgr is None:
        _mgr = socketio.AsyncRedisManager(settings.redis_url, channel="valo", write_only=True)
    return _mgr


async def emit(event: str, data: Any, rooms: list[str], durable: bool = True) -> None:
    body = msgspec.to_builtins(data)
    try:
        seq = None
        if durable:
            seq = await kv().xadd(
                STREAM, {"e": event, "r": ",".join(rooms), "d": json.dumps(body)}, maxlen=5000, approximate=True
            )
        await manager().emit(event, {"seq": seq, "d": body}, to=rooms)
    except Exception as e:
        _log.warning("realtime_emit_failed", kind=event, rooms=rooms, error=str(e))


async def since(seq: str, limit: int = 500) -> list[tuple[str, str, list[str], Any]]:
    rows = await kv().xrange(STREAM, min=f"({seq}", count=limit)
    return [(sid, f["e"], f["r"].split(","), json.loads(f["d"])) for sid, f in rows]


def _key(seq: str) -> tuple[int, ...]:
    return tuple(int(x) for x in seq.split("-"))


async def known(seq: str) -> bool:
    first = await kv().xrange(STREAM, count=1)
    try:
        return bool(first) and _key(first[0][0]) <= _key(seq)
    except ValueError:
        return False
