import json
import re
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import after, now
from app.db.models import Command, Device, History, Room, Stat
from app.domain import adapters, events
from app.domain.common import UNSET, Principal, S, Unset, after_cursor, cursor, out, patch
from app.lib import log, mqtt, realtime, tasks
from app.lib.errors import ApplicationError
from app.lib.kv import kv
from app.lib.settings import env_int, settings

COMMAND_TIMEOUT = env_int("COMMAND_TIMEOUT", 5)
_log = log.get("devices")


class DeviceOut(S):
    id: str
    name: str
    room_id: str | None
    source: str
    kind: str
    model: str
    vendor: str
    address: str
    ieee: str | None
    ext_id: str | None
    caps: list[dict[str, Any]]
    state: dict[str, Any]
    attrs: dict[str, Any]
    available: bool
    disabled: bool
    last_seen: datetime | None
    service: bool = False


SERVICE_KINDS = frozenset({"weather", "air", "calendar", "clock", "timer", "meter", "presence", "plugguard"})


def is_service(source: str, kind: str, declared: Any = None) -> bool:
    """Запись расширения, которая описывает сервис (погода, календарь, учет, охрана), а не устройство.

    Расширение объявляет это само (`service` в метаданных записи), без объявления решает вид записи.
    """
    if source != "ext":
        return False
    return declared if isinstance(declared, bool) else kind in SERVICE_KINDS


class DevicePatch(S):
    name: str | Unset = UNSET
    room_id: str | Unset | None = UNSET
    disabled: bool | Unset = UNSET
    kind: str | Unset = UNSET


class CommandIn(S):
    values: dict[str, Any]


class CommandOut(S):
    id: uuid.UUID
    device_id: str
    values: dict[str, Any]
    status: str
    actor: str
    created_at: datetime
    done_at: datetime | None
    error: str | None = None


class MapCap(S):
    id: str
    type: str
    topic: str
    path: str = ""
    unit: str | None = None
    cmd: str | None = None
    tpl: str | None = None
    on: str = "ON"
    off: str = "OFF"


class MappingIn(S):
    id: str
    name: str
    room_id: str | None = None
    kind: str | None = None
    caps: list[MapCap] = []


def view(d: Device) -> DeviceOut:
    o = out(d, DeviceOut)
    meta = d.attrs.get("meta")
    o.service = is_service(d.source, d.kind, meta.get("service") if isinstance(meta, dict) else None)
    o.attrs = {k: v for k, v in d.attrs.items() if k not in ("conv", "h", "changed")} | {
        "changed": d.attrs.get("changed", {})
    }
    return o


def rooms_of(d: Device) -> list[str]:
    return [f"room:{d.room_id or 'none'}", f"dev:{d.id}", "rooms:all"]


async def get(s: AsyncSession, device_id: str) -> Device:
    d = await s.get(Device, device_id)
    if d is None:
        raise ApplicationError("device_not_found", 404)
    return d


async def listing(s: AsyncSession, p: Principal, room: str = "", source: str = "", q: str = "") -> list[DeviceOut]:
    st = select(Device).order_by(Device.name)
    if room:
        st = st.where(Device.room_id == room)
    if source:
        st = st.where(Device.source == source)
    if q:
        like = f"%{q}%"
        st = st.where(
            Device.name.ilike(like) | Device.model.ilike(like) | Device.id.ilike(like) | Device.ieee.ilike(like)
        )
    if p.rooms:
        st = st.where(Device.room_id.in_(p.rooms))
    return [view(d) for d in (await s.scalars(st)).all()]


async def upsert(s: AsyncSession, device_id: str, source: str, name: str, **fields: Any) -> tuple[Device, bool]:
    d = await s.get(Device, device_id)
    created = d is None
    if d is None:
        d = Device(id=device_id, source=source, name=name, state={}, attrs={}, caps=[], available=True)
        s.add(d)
    dirty = created
    attrs = d.attrs or {}
    default = d.name == (attrs.get("meta") or {}).get("name", d.name)
    if not created and source == "ext" and name and name != d.name and default and not attrs.get("nameSet"):
        d.name = name
        dirty = True
    for k, v in fields.items():
        if k == "kind" and (d.attrs or {}).get("kindSet"):
            continue
        if k == "attrs":
            v = {**(d.attrs or {}), **v}
        if getattr(d, k, None) != v:
            setattr(d, k, v)
            dirty = True
    if not dirty:
        return d, False
    if created:
        await s.flush()
        await events.add(
            s,
            "device.added",
            "ok",
            params={"name": name, "source": source, "model": d.model},
            device_id=d.id,
            room_id=d.room_id,
        )
    snapshot = view(d)
    after(s, lambda: realtime.emit("device", snapshot, rooms_of(d)))
    return d, created


async def update(s: AsyncSession, p: Principal, device_id: str, data: DevicePatch) -> DeviceOut:
    d = await get(s, device_id)
    p.need_room(d.room_id)
    p.need("admin")
    if not isinstance(data.room_id, Unset) and data.room_id and await s.get(Room, data.room_id) is None:
        raise ApplicationError("room_not_found", 404)
    if not isinstance(data.kind, Unset) and not re.fullmatch(r"[a-z][a-z0-9_]{1,23}", data.kind):
        raise ApplicationError("validation", 422, detail="kind")
    old_room, old_name = d.room_id, d.name
    changed = patch(d, data)
    if "kind" in changed:
        d.attrs = {**d.attrs, "kindSet": True}
    if "name" in changed:
        d.attrs = {**d.attrs, "nameSet": True}
    if "name" in changed:
        await events.add(
            s,
            "device.renamed",
            actor=p.actor,
            params={"name": d.name, "old": old_name},
            device_id=d.id,
            room_id=d.room_id,
        )
    if "room_id" in changed:
        await events.add(
            s,
            "device.moved",
            actor=p.actor,
            params={"name": d.name, "room": d.room_id, "old": old_room},
            device_id=d.id,
            room_id=d.room_id,
        )
    snapshot = view(d)
    after(s, lambda: realtime.emit("device", snapshot, list({*rooms_of(d), f"room:{old_room or 'none'}"})))
    return snapshot


async def remove(s: AsyncSession, p: Principal, device_id: str, force: bool = False) -> None:
    d = await get(s, device_id)
    p.need("admin")
    msgs: list[tuple[str, Any, bool]] = []
    if d.source == "zigbee":
        msgs.append(
            (f"{settings.z2m_topic}/bridge/request/device/remove", {"id": d.ieee or d.address, "force": force}, False)
        )
    elif d.source == "mqtt":
        msgs += [(f"hub/v1/dev/{d.address}/meta", "", True), (f"hub/v1/dev/{d.address}/avail", "", True)]
    elif d.source == "ha":
        msgs += [(t, "", True) for t in d.attrs.get("configs", [])]
    await events.add(
        s,
        "device.removed",
        "warn",
        actor=p.actor,
        params={"name": d.name, "source": d.source, "force": force},
        device_id=d.id,
        room_id=d.room_id,
    )
    rooms = rooms_of(d)
    await s.delete(d)

    async def push() -> None:
        for topic, payload, retain in msgs:
            await mqtt.publish(topic, payload, qos=1, retain=retain)
        await realtime.emit("device_gone", {"id": device_id}, rooms)

    after(s, push)


def _hist(d: Device, cap: dict[str, Any], v: Any, ts: datetime) -> History | None:
    t = cap.get("type")
    if t == "num" and isinstance(v, (int, float)) and not isinstance(v, bool):
        last = (d.attrs.get("h") or {}).get(cap["id"])
        if last and ts.timestamp() - last[0] < 60 and abs(v - last[1]) < max(abs(last[1]) * 0.03, 0.2):
            return None
        d.attrs = {**d.attrs, "h": {**(d.attrs.get("h") or {}), cap["id"]: [ts.timestamp(), v]}}
        return History(device_id=d.id, cap=cap["id"], ts=ts, num=float(v))
    if t == "bool" and isinstance(v, bool):
        return History(device_id=d.id, cap=cap["id"], ts=ts, num=1.0 if v else 0.0)
    if t in ("enum", "text") and v is not None:
        return History(device_id=d.id, cap=cap["id"], ts=ts, txt=str(v)[:255])
    return None


async def apply(s: AsyncSession, d: Device, values: dict[str, Any], cause_id: int | None = None) -> dict[str, Any]:
    ts = now()
    caps = {c["id"]: c for c in d.caps}
    changes = {k: (d.state.get(k), v) for k, v in values.items() if d.state.get(k) != v or (k == "action" and v)}
    d.last_seen = ts
    if not d.available:
        await set_available(s, d, True)
    if not changes:
        await _confirm(s, d)
        return {}
    d.state = {**d.state, **{k: v[1] for k, v in changes.items()}}
    d.attrs = {**d.attrs, "changed": {**(d.attrs.get("changed") or {}), **{k: ts.isoformat() for k in changes}}}
    for k, (old, new) in changes.items():
        cap = caps.get(
            k, {"id": k, "type": "num" if isinstance(new, (int, float)) and not isinstance(new, bool) else "text"}
        )
        h = _hist(d, cap, new, ts)
        if h is not None:
            s.add(h)
        if k == "action" and new:
            await events.add(
                s,
                "device.action",
                params={"name": d.name, "value": new},
                device_id=d.id,
                room_id=d.room_id,
                cause_id=cause_id,
            )
        elif k in adapters.LOGGED and old is not None:
            level = "crit" if k in adapters.ALARMS and new else "info"
            await events.add(
                s,
                "device.state",
                level,
                params={"name": d.name, "cap": k, "value": new},
                device_id=d.id,
                room_id=d.room_id,
                cause_id=cause_id,
            )
        if k in adapters.ALARMS:
            key = f"{k}:{d.id}"
            if new:
                await events.notify(s, key, "crit", adapters.ALARMS[k], {"name": d.name}, f"devices/{d.id}")
            else:
                await events.resolve(s, key)
        if k == "bat" and isinstance(new, (int, float)):
            if new < 15:
                await events.notify(
                    s, f"bat:{d.id}", "warn", "battery_low", {"name": d.name, "value": new}, f"devices/{d.id}"
                )
            elif new >= 20:
                await events.resolve(s, f"bat:{d.id}")
    await _confirm(s, d)
    delta = {k: v[1] for k, v in changes.items()}
    payload = {"id": d.id, "s": delta, "t": ts.isoformat()}
    trig = {k: [o, n] for k, (o, n) in changes.items()}
    rooms = rooms_of(d)

    async def push() -> None:
        await realtime.emit("state", payload, rooms)
        if await events.wants(f"state:{d.id}", f"wait:{d.id}", f"action:{d.id}"):
            await tasks.kick(
                "flows.dispatch", event={"type": "state", "device": d.id, "changes": trig, "cause": cause_id}
            )
        if settings.mqtt_user:
            await mqtt.publish(f"hub/v1/core/state/{d.id}", delta)

    after(s, push)
    return delta


async def set_available(s: AsyncSession, d: Device, available: bool) -> None:
    if d.available == available:
        return
    d.available = available
    key = f"offline:{d.id}"
    if available:
        await events.add(s, "device.online", "ok", params={"name": d.name}, device_id=d.id, room_id=d.room_id)
        await events.resolve(s, key)
    else:
        await events.add(s, "device.offline", "warn", params={"name": d.name}, device_id=d.id, room_id=d.room_id)
        await events.notify(s, key, "warn", "device_offline", {"name": d.name}, f"devices/{d.id}")
    payload = {"id": d.id, "a": available}
    rooms = rooms_of(d)
    after(s, lambda: realtime.emit("state", payload, rooms))


async def ext_offline(s: AsyncSession, ext_id: str) -> int:
    """Расширение отключилось от брокера: его записи больше никто не обновляет, показываем их без связи."""
    rows = (await s.scalars(select(Device).where(Device.ext_id == ext_id, Device.available.is_(True)))).all()
    for d in rows:
        await set_available(s, d, False)
    return len(rows)


async def _confirm(s: AsyncSession, d: Device) -> None:
    if not await kv().scard(f"cmd:pending:{d.id}"):
        return
    rows = (await s.scalars(select(Command).where(Command.device_id == d.id, Command.status == "pending"))).all()
    for c in rows:
        if all(d.state.get(k) == v for k, v in c.values.items()):
            await finish(s, c, "ok", d)


async def finish(s: AsyncSession, c: Command, status: str, d: Device | None = None, error: str | None = None) -> None:
    d = d or await s.get(Device, c.device_id)
    c.status, c.done_at, c.error = status, now(), error
    name = d.name if d else c.device_id
    room = d.room_id if d else None
    if status == "ok":
        ev = await events.add(
            s,
            "command.ok",
            "ok",
            actor=c.actor,
            params={"name": name, "values": c.values},
            device_id=c.device_id,
            room_id=room,
            cause_id=c.cause_id,
        )
    else:
        ev = await events.add(
            s,
            f"command.{status}",
            "crit",
            actor=c.actor,
            params={"name": name, "values": c.values, "error": error},
            device_id=c.device_id,
            room_id=room,
            cause_id=c.cause_id,
        )
    snapshot = out(c, CommandOut)
    rooms = [f"room:{room or 'none'}", f"dev:{c.device_id}", "rooms:all"]
    cid, group = str(c.id), c.group_id

    async def push() -> None:
        await kv().srem(f"cmd:pending:{snapshot.device_id}", cid)
        await tasks.cancel(f"cmd:{cid}")
        await realtime.emit("cmd", snapshot, rooms)
        if group:
            await _group(group, status == "ok", name, ev.id)

    after(s, push)


async def _group(group: str, ok: bool, name: str, event_id: int) -> None:
    key = f"grp:{group}"
    pipe = kv().pipeline()
    pipe.hincrby(key, "done", 1)
    if not ok:
        pipe.rpush(f"{key}:failed", name)
    await pipe.execute()
    g = await kv().hgetall(key)
    if not g or int(g.get("done", 0)) < int(g.get("total", 0)):
        return
    if not await kv().delete(key):
        return
    failed = await kv().lrange(f"{key}:failed", 0, -1)
    await kv().delete(f"{key}:failed")
    await tasks.kick(
        "scenes.done",
        group=group,
        scene=g.get("scene", ""),
        name=g.get("name", ""),
        actor=g.get("actor", ""),
        total=int(g["total"]),
        failed=failed,
        cause=int(g.get("cause") or 0) or None,
    )


async def command(
    s: AsyncSession,
    p: Principal,
    device_id: str,
    values: dict[str, Any],
    actor: str | None = None,
    cause_id: int | None = None,
    group: str | None = None,
) -> CommandOut:
    d = await get(s, device_id)
    p.need("member")
    p.need_room(d.room_id)
    caps = {c["id"]: c for c in d.caps}
    clean = {}
    for k, v in values.items():
        if k not in caps:
            raise ApplicationError("cap_unknown", 422, cap=k)
        if v == "toggle" and caps[k].get("type") == "bool":
            v = not d.state.get(k)
        clean[k] = adapters.validate(caps[k], v)
    msgs = _outbound(d, clean)
    c = Command(
        device_id=d.id, values=clean, actor=actor or p.actor, cause_id=cause_id, group_id=group, created_at=now()
    )
    s.add(c)
    await s.flush()
    cid = str(c.id)
    snapshot = out(c, CommandOut)
    rooms = rooms_of(d)
    _log.info("command", device=d.id, values=clean, actor=c.actor, command_id=cid)

    async def push() -> None:
        await kv().sadd(f"cmd:pending:{d.id}", cid)
        await tasks.later(f"cmd:{cid}", COMMAND_TIMEOUT, "commands.timeout", id=cid)
        await realtime.emit("cmd", snapshot, rooms)
        for topic, payload in msgs(cid):
            await mqtt.publish(topic, payload, qos=1, properties=mqtt.props(expiry=COMMAND_TIMEOUT * 2))

    after(s, push)
    return snapshot


def _outbound(d: Device, values: dict[str, Any]):
    if d.source == "zigbee":
        payload = adapters.z2m_out(d.attrs.get("conv") or {}, values)
        return lambda cid: [(f"{settings.z2m_topic}/{d.address}/set", payload)]
    if d.source == "mqtt":
        return lambda cid: [(f"hub/v1/dev/{d.address}/set", {"cmd": cid, "values": values})]
    if d.source == "ext":
        return lambda cid: [(f"hub/v1/ext/{d.ext_id}/dev/{d.address}/set", {"cmd": cid, "values": values})]
    if d.source == "ha":
        msgs = adapters.ha_out(d.attrs.get("conv") or {}, values)
        return lambda cid: msgs
    if d.source == "map":
        msgs = adapters.map_out(d.attrs.get("map") or [], values)
        return lambda cid: msgs
    raise ApplicationError("cap_not_writable", 422, cap=",".join(values))


async def timeout(s: AsyncSession, command_id: str) -> None:
    c = await s.get(Command, uuid.UUID(command_id))
    if c is None or c.status != "pending":
        return
    d = await s.get(Device, c.device_id)
    await finish(s, c, "timeout", d)
    if d:
        await events.notify(s, f"cmdto:{d.id}", "warn", "command_timeout", {"name": d.name}, f"devices/{d.id}")


async def ack(s: AsyncSession, d: Device, data: dict[str, Any]) -> None:
    try:
        c = await s.get(Command, uuid.UUID(str(data.get("cmd"))))
    except ValueError:
        return
    if c is None or c.status != "pending":
        return
    if data.get("ok", True):
        if isinstance(data.get("values"), dict):
            await apply(s, d, data["values"])
        if c.status == "pending":
            await finish(s, c, "ok", d)
    else:
        await finish(s, c, "fail", d, str(data.get("error") or ""))


async def commands(s: AsyncSession, device_id: str, limit: int = 30, before: str | None = None) -> list[CommandOut]:
    st = (
        select(Command)
        .where(Command.device_id == device_id)
        .order_by(Command.created_at.desc(), Command.id.desc())
        .limit(limit)
    )
    if cur := cursor(before):
        st = st.where(after_cursor(Command.created_at, Command.id, cur))
    return [out(c, CommandOut) for c in (await s.scalars(st)).all()]


async def history(s: AsyncSession, device_id: str, cap: str, hours: float = 24) -> dict[str, Any]:
    start = now() - timedelta(hours=hours)
    if hours <= 48:
        rows = (
            await s.execute(
                select(History.ts, History.num, History.txt)
                .where(History.device_id == device_id, History.cap == cap, History.ts >= start)
                .order_by(History.ts)
            )
        ).all()
        return {
            "cap": cap,
            "kind": "raw",
            "points": [[r.ts.timestamp(), r.num if r.num is not None else r.txt] for r in rows],
        }
    rows = (
        (
            await s.execute(
                select(Stat).where(Stat.device_id == device_id, Stat.cap == cap, Stat.hour >= start).order_by(Stat.hour)
            )
        )
        .scalars()
        .all()
    )
    return {"cap": cap, "kind": "hourly", "points": [[r.hour.timestamp(), r.mean, r.min, r.max] for r in rows]}


async def aggregate(s: AsyncSession, hours: int = 3) -> int:
    end = now().replace(minute=0, second=0, microsecond=0)
    start = end - timedelta(hours=hours)
    hour = func.date_trunc("hour", History.ts)
    rows = (
        await s.execute(
            select(
                History.device_id,
                History.cap,
                hour.label("h"),
                func.avg(History.num),
                func.min(History.num),
                func.max(History.num),
                func.count(),
            )
            .where(History.ts >= start, History.ts < end, History.num.is_not(None))
            .group_by(History.device_id, History.cap, hour)
        )
    ).all()
    for dev, cap, h, mean, lo, hi, n in rows:
        last = await s.scalar(
            select(History.num)
            .where(History.device_id == dev, History.cap == cap, History.ts >= h, History.ts < h + timedelta(hours=1))
            .order_by(History.ts.desc())
            .limit(1)
        )
        await s.merge(
            Stat(
                device_id=dev, cap=cap, hour=h, mean=mean, min=lo, max=hi, last=last if last is not None else mean, n=n
            )
        )
    return len(rows)


async def purge(s: AsyncSession, days: int) -> int:
    res = await s.execute(delete(History).where(History.ts < now() - timedelta(days=days)))
    return res.rowcount or 0


async def mapped(s: AsyncSession, p: Principal, data: MappingIn) -> DeviceOut:
    p.need("admin")
    if not data.caps:
        raise ApplicationError("validation", 422, detail="caps")
    rows = [
        {
            k: v
            for k, v in {
                "id": c.id,
                "type": c.type,
                "unit": c.unit,
                "topic": c.topic,
                "path": c.path,
                "cmd": c.cmd,
                "tpl": c.tpl,
                "on": c.on,
                "off": c.off,
            }.items()
            if v is not None
        }
        for c in data.caps
    ]
    caps = [
        {"id": r["id"], "type": r["type"], "access": "r" + ("w" if r.get("cmd") else "")}
        | ({"unit": r["unit"]} if r.get("unit") else {})
        for r in rows
    ]
    existing = await s.get(Device, data.id)
    if existing is not None and existing.source != "map":
        raise ApplicationError("device_exists", 409)
    d, _ = await upsert(
        s,
        data.id,
        "map",
        data.name,
        caps=caps,
        kind=adapters.kind_of(caps, data.kind),
        room_id=data.room_id,
        address=rows[0]["topic"],
        attrs={"map": rows},
    )
    after(s, lambda: kv().publish("mqtt:index", "1"))
    return view(d)


async def summary(s: AsyncSession, p: Principal) -> dict[str, Any]:
    st = select(Device)
    if p.rooms:
        st = st.where(Device.room_id.in_(p.rooms))
    ds = (await s.scalars(st)).all()
    lights = [d for d in ds if d.kind == "light"]
    return {
        "devices": len(ds),
        "offline": sum(1 for d in ds if not d.available),
        "lightsOn": sum(1 for d in lights if d.state.get("on") and d.available),
        "lights": len(lights),
        "open": sum(1 for d in ds if d.kind == "contact" and d.state.get("open")),
        "leaks": sum(1 for d in ds if d.state.get("leak")),
        "power": sum(float(d.state.get("w") or 0) for d in ds if d.kind == "meter"),
        "lowBattery": sum(1 for d in ds if isinstance(d.state.get("bat"), (int, float)) and d.state["bat"] < 15),
    }


async def index(s: AsyncSession) -> dict[str, list[list[str]]]:
    idx: dict[str, list[list[str]]] = {}
    for d in (await s.scalars(select(Device).where(Device.source.in_(("ha", "map"))))).all():
        conv = d.attrs.get("conv") or {}
        topics = (
            {c.get("st") for c in conv.values()}
            if d.source == "ha"
            else {r.get("topic") for r in d.attrs.get("map") or []}
        )
        for t in topics - {None}:
            idx.setdefault(t, []).append([d.id, d.source])
        if d.source == "ha":
            for t in {c.get("avail") for c in conv.values()} - {None}:
                idx.setdefault(t, []).append([d.id, "avail"])
    await kv().set("mqtt:index:data", json.dumps(idx))
    return idx
