import hashlib
import json
import logging
import re
import time
import traceback
from typing import Any

from redis import Redis

from app.lib.settings import settings

ITEMS = "errors:items"
INDEX = "errors:index"
SEEN = "errors:seen"
LIMIT = 300
_SKIP = {"event", "level", "logger", "timestamp", "process", "exc_info", "_record", "_from_structlog"}


_VARIABLE = [
    (re.compile(r"Task-\d+"), "Task-N"),
    (re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I), "<uuid>"),
    (re.compile(r"\b0x[0-9a-f]{6,}\b", re.I), "0x<addr>"),
    (re.compile(r"\d{5,}"), "<n>"),
]


def normalize(event: str) -> str:
    """Убирает из текста ошибки номера задач, адреса и идентификаторы, чтобы одинаковые ошибки группировались."""
    for rx, rep in _VARIABLE:
        event = rx.sub(rep, event)
    return event


def fingerprint(process: str, logger: str, event: str) -> str:
    return hashlib.sha1(f"{process}|{logger}|{normalize(event)}".encode()).hexdigest()[:16]


def entry(process: str, logger: str, event: str, level: str, detail: str, trace: str, ts: float) -> dict[str, Any]:
    return {
        "id": fingerprint(process, logger, event),
        "process": process,
        "logger": logger,
        "event": event[:300],
        "level": level,
        "detail": detail[:2000],
        "trace": trace[-6000:],
        "first": ts,
        "last": ts,
        "count": 1,
    }


def merge(old: dict[str, Any] | None, new: dict[str, Any]) -> dict[str, Any]:
    if not old:
        return new
    return {**new, "first": old.get("first", new["first"]), "count": int(old.get("count", 0)) + 1}


def store(r: Redis, item: dict[str, Any]) -> None:
    raw = r.hget(ITEMS, item["id"])
    cur = merge(json.loads(raw) if raw else None, item)
    pipe = r.pipeline()
    pipe.hset(ITEMS, item["id"], json.dumps(cur, default=str))
    pipe.zadd(INDEX, {item["id"]: cur["last"]})
    pipe.execute()
    extra = r.zcard(INDEX) - LIMIT
    if extra > 0:
        old = r.zrange(INDEX, 0, extra - 1)
        if old:
            r.hdel(ITEMS, *old)
            r.zrem(INDEX, *old)


async def astore(item: dict[str, Any]) -> None:
    from app.lib.kv import kv

    raw = await kv().hget(ITEMS, item["id"])
    cur = merge(json.loads(raw) if raw else None, item)
    await kv().hset(ITEMS, item["id"], json.dumps(cur, default=str))
    await kv().zadd(INDEX, {item["id"]: cur["last"]})
    extra = await kv().zcard(INDEX) - LIMIT
    if extra > 0:
        old = await kv().zrange(INDEX, 0, extra - 1)
        if old:
            await kv().hdel(ITEMS, *old)
            await kv().zrem(INDEX, *old)


_EXT_LINE = re.compile(r"^\S+ \S+ (ERROR|CRITICAL) (.*)$")


def ext_line(ext_id: str, text: str) -> dict[str, Any] | None:
    m = _EXT_LINE.match(text)
    if not m:
        return None
    msg = m.group(2).strip()
    event = re.sub(r"\d+", "N", msg)[:160]
    return entry(f"ext:{ext_id}", ext_id, event, m.group(1).lower(), msg[:2000], "", time.time())


class Handler(logging.Handler):
    def __init__(self, process: str) -> None:
        super().__init__(logging.ERROR)
        self.process = process
        self._redis: Redis | None = None
        self._busy = False

    def redis(self) -> Redis:
        if self._redis is None:
            self._redis = Redis.from_url(settings.redis_url, decode_responses=True, socket_timeout=1)
        return self._redis

    def emit(self, record: logging.LogRecord) -> None:
        if self._busy:
            return
        self._busy = True
        try:
            ev = record.msg if isinstance(record.msg, dict) else {}
            event = str(ev.get("event") or record.getMessage())
            detail = {k: v for k, v in ev.items() if k not in _SKIP}
            trace = ""
            exc = ev.get("exc_info")
            if record.exc_info:
                trace = "".join(traceback.format_exception(*record.exc_info))
            elif isinstance(exc, BaseException):
                trace = "".join(traceback.format_exception(exc))
            elif exc:
                trace = traceback.format_exc()
                trace = "" if trace.startswith("NoneType: None") else trace
            item = entry(
                str(ev.get("process") or self.process),
                str(ev.get("logger") or record.name),
                event,
                record.levelname.lower(),
                json.dumps(detail, ensure_ascii=False, default=str) if detail else "",
                trace,
                time.time(),
            )
            store(self.redis(), item)
        except Exception:
            self.handleError(record)
        finally:
            self._busy = False
