from datetime import datetime
from typing import Any

from sqlalchemy import String, cast, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import after, now
from app.db.models import Event, Home, Notification
from app.domain.common import Principal, S, out
from app.lib import log, realtime, tasks
from app.lib.errors import ApplicationError
from app.lib.kv import kv

_log = log.get("events")
LEVELS = {"info": 0, "ok": 0, "warn": 1, "crit": 2}


class EventOut(S):
    id: int
    ts: datetime
    type: str
    level: str
    params: dict[str, Any]
    actor: str
    device_id: str | None
    flow_id: str | None
    room_id: str | None
    cause_id: int | None


class NotificationOut(S):
    id: int
    key: str
    level: str
    type: str
    params: dict[str, Any]
    route: str
    created_at: datetime


def rooms(room_id: str | None) -> list[str]:
    return ["all", f"room:{room_id}"] if room_id else ["all"]


async def wants(*keys: str) -> bool:
    return any(await kv().smismember("flows:trig", list(keys)))


async def add(
    s: AsyncSession,
    type: str,
    level: str = "info",
    actor: str = "system",
    params: dict[str, Any] | None = None,
    device_id: str | None = None,
    room_id: str | None = None,
    flow_id: str | None = None,
    cause_id: int | None = None,
) -> Event:
    ev = Event(
        type=type,
        level=level,
        actor=actor,
        params=params or {},
        device_id=device_id,
        room_id=room_id,
        flow_id=flow_id,
        cause_id=cause_id,
        ts=now(),
    )
    s.add(ev)
    await s.flush()
    _log.info("event", type=type, level=level, actor=actor, device=device_id, flow=flow_id, event_id=ev.id)

    async def push() -> None:
        await realtime.emit("event", out(ev, EventOut), rooms(room_id) + ([f"flow:{flow_id}"] if flow_id else []))
        if await wants("log"):
            await tasks.kick(
                "flows.dispatch",
                event={
                    "type": "log",
                    "event": type,
                    "level": level,
                    "id": ev.id,
                    "params": params or {},
                    "device": device_id,
                    "room": room_id,
                },
            )

    after(s, push)
    return ev


async def listing(
    s: AsyncSession,
    p: Principal,
    kind: str = "",
    level: str = "",
    q: str = "",
    device: str = "",
    flow: str = "",
    before: int | None = None,
    limit: int = 100,
) -> list[EventOut]:
    st = select(Event).order_by(Event.id.desc()).limit(min(limit, 500))
    if kind:
        st = st.where(Event.type.startswith(kind))
    if level:
        st = st.where(Event.level == level)
    if device:
        st = st.where(Event.device_id == device)
    if flow:
        st = st.where(Event.flow_id == flow)
    if before:
        st = st.where(Event.id < before)
    if q:
        like = f"%{q}%"
        st = st.where(or_(Event.type.ilike(like), Event.actor.ilike(like), cast(Event.params, String).ilike(like)))
    if p.rooms:
        st = st.where(Event.room_id.in_(p.rooms))
    return [out(e, EventOut) for e in (await s.scalars(st)).all()]


async def chain(s: AsyncSession, event_id: int) -> list[EventOut]:
    items, cur, seen = [], await s.get(Event, event_id), set()
    if cur is None:
        raise ApplicationError("not_found", 404)
    while cur is not None and cur.id not in seen and len(items) < 20:
        seen.add(cur.id)
        items.append(out(cur, EventOut))
        cur = await s.get(Event, cur.cause_id) if cur.cause_id else None
    return list(reversed(items))


async def notify(
    s: AsyncSession,
    key: str,
    level: str,
    type: str,
    params: dict[str, Any],
    route: str = "",
    force: bool = False,
    touch: bool = False,
) -> Notification:
    """Создать или обновить уведомление по ключу. touch переносит время на сейчас и для еще не снятого уведомления."""
    n = await s.scalar(select(Notification).where(Notification.key == key))
    fresh = n is None or n.dismissed_at is not None
    if n is None:
        n = Notification(key=key, level=level, type=type, params=params, route=route, created_at=now())
        s.add(n)
    else:
        n.level, n.type, n.params, n.route, n.dismissed_at = level, type, params, route, None
        if fresh or touch:
            n.created_at = now()
    await s.flush()

    async def push() -> None:
        await realtime.emit("notif", out(n, NotificationOut), ["all"])
        if fresh:
            await tasks.kick("ext.push", type=type, level=level, params=params, force=force)

    after(s, push)
    return n


async def resolve(s: AsyncSession, key: str) -> None:
    n = await s.scalar(select(Notification).where(Notification.key == key, Notification.dismissed_at.is_(None)))
    if n:
        n.dismissed_at = now()
        nid = n.id
        after(s, lambda: realtime.emit("notif_gone", {"id": nid}, ["all"]))


async def dismiss(s: AsyncSession, nid: int) -> None:
    n = await s.get(Notification, nid)
    if n is None:
        raise ApplicationError("not_found", 404)
    n.dismissed_at = now()
    after(s, lambda: realtime.emit("notif_gone", {"id": nid}, ["all"]))


async def active(s: AsyncSession) -> list[NotificationOut]:
    st = select(Notification).where(Notification.dismissed_at.is_(None)).order_by(Notification.created_at.desc())
    return [out(n, NotificationOut) for n in (await s.scalars(st)).all()]


async def home(s: AsyncSession) -> Home:
    h = await s.get(Home, 1)
    if h is None:
        h = Home(id=1)
        s.add(h)
        await s.flush()
    return h
