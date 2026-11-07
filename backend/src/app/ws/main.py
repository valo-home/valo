import asyncio
import uuid
from typing import Any

import socketio
from sqlalchemy import select

from app.db.base import session
from app.db.models import Chat, Device
from app.domain import auth
from app.domain.common import Principal
from app.lib import log, realtime
from app.lib.kv import beat
from app.lib.settings import env, settings

log.setup("ws")
_log = log.get("ws")
_origins = env("WS_CORS", "*")
sio = socketio.AsyncServer(
    async_mode="asgi",
    client_manager=socketio.AsyncRedisManager(settings.redis_url, channel="valo"),
    cors_allowed_origins="*" if _origins == "*" else [o.strip() for o in _origins.split(",")],
    logger=False,
    engineio_logger=False,
)


async def _principal(sid: str) -> Principal | None:
    data = await sio.get_session(sid)
    return Principal(**data["p"]) if data and data.get("p") else None


async def _allowed(p: Principal, room: str) -> bool:
    if room in ("zigbee", "mqtt") or room.startswith("extlog:"):
        return p.level() >= 2
    if room.startswith("flow:"):
        return not p.rooms
    if room.startswith("dev:"):
        if not p.rooms:
            return True
        async with session() as s:
            d = await s.scalar(select(Device).where(Device.id == room[4:]))
            return bool(d and d.room_id in p.rooms)
    if room.startswith("room:"):
        return p.room_ok(room[5:])
    if room.startswith("chat:"):
        try:
            cid = uuid.UUID(room[5:])
        except ValueError:
            return False
        async with session() as s:
            c = await s.get(Chat, cid)
            return bool(c and str(c.user_id) == p.id)
    return False


@sio.event
async def connect(sid: str, environ: dict[str, Any], data: dict[str, Any] | None = None) -> None:
    ticket = (data or {}).get("ticket", "")
    async with session() as s:
        p = await auth.ws_principal(s, ticket) if ticket else None
    if p is None:
        _log.info("ws_refused", sid=sid)
        raise socketio.exceptions.ConnectionRefusedError("unauthorized")
    await sio.save_session(
        sid,
        {"p": {"id": p.id, "username": p.username, "name": p.name, "role": p.role, "rooms": p.rooms, "scope": p.scope}},
    )
    await sio.enter_room(sid, "any")
    await sio.enter_room(sid, f"user:{p.id}")
    if p.rooms:
        for r in p.rooms:
            await sio.enter_room(sid, f"room:{r}")
    else:
        await sio.enter_room(sid, "all")
        await sio.enter_room(sid, "rooms:all")
    _log.info("ws_connected", sid=sid, user=p.username)


@sio.event
async def disconnect(sid: str, reason: Any = None) -> None:
    _log.info("ws_disconnected", sid=sid)


@sio.event
async def sub(sid: str, data: dict[str, Any]) -> dict[str, Any]:
    p = await _principal(sid)
    if p is None:
        return {"ok": False}
    joined = []
    for room in (data or {}).get("rooms", [])[:20]:
        if isinstance(room, str) and await _allowed(p, room):
            await sio.enter_room(sid, room)
            joined.append(room)
    return {"ok": True, "rooms": joined}


@sio.event
async def unsub(sid: str, data: dict[str, Any]) -> dict[str, Any]:
    for room in (data or {}).get("rooms", [])[:20]:
        if (
            isinstance(room, str)
            and room not in ("all", "rooms:all", "any")
            and not room.startswith(("room:", "user:"))
        ):
            await sio.leave_room(sid, room)
    return {"ok": True}


@sio.event
async def resume(sid: str, data: dict[str, Any]) -> dict[str, Any]:
    seq = str((data or {}).get("seq") or "")
    if not seq or not await realtime.known(seq):
        return {"ok": False, "resync": True}
    mine = set(sio.rooms(sid))
    sent = 0
    for sq, event, rooms, body in await realtime.since(seq):
        if mine.intersection(rooms):
            await sio.emit(event, {"seq": sq, "d": body}, to=sid)
            sent += 1
    return {"ok": True, "sent": sent}


async def _beat() -> None:
    while True:
        try:
            await beat("ws", 30)
        except Exception as e:
            _log.warning("ws_beat_failed", error=str(e))
        await asyncio.sleep(10)


_tasks: set[asyncio.Task] = set()


async def _startup() -> None:
    t = asyncio.create_task(_beat())
    _tasks.add(t)


app = socketio.ASGIApp(sio, socketio_path="/socket.io", on_startup=_startup)
