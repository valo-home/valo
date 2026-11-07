from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import after
from app.db.models import Dashboard, Home, Room
from app.domain import auth, events
from app.domain.common import UNSET, Principal, S, Unset, out, patch, slug
from app.lib import realtime
from app.lib.errors import ApplicationError
from app.lib.kv import alive, get_json, kv
from app.lib.settings import environment
from app.lib.timeutil import zone


class HomeOut(S):
    name: str
    lat: float
    lon: float
    timezone: str
    currency: str
    price_area: str
    setup_done: bool
    settings: dict[str, Any]


class HomePatch(S):
    name: str | Unset = UNSET
    lat: float | Unset = UNSET
    lon: float | Unset = UNSET
    timezone: str | Unset = UNSET
    currency: str | Unset = UNSET
    price_area: str | Unset = UNSET
    settings: dict[str, Any] | Unset = UNSET


class RoomOut(S):
    id: str
    name: str
    floor: int
    outdoor: bool
    geom: dict[str, Any]
    sort: int


class RoomIn(S):
    name: str
    floor: int = 1
    outdoor: bool = False
    geom: dict[str, Any] = {}
    sort: int = 0
    id: str | None = None


class RoomPatch(S):
    name: str | Unset = UNSET
    floor: int | Unset = UNSET
    outdoor: bool | Unset = UNSET
    geom: dict[str, Any] | Unset = UNSET
    sort: int | Unset = UNSET


class DashOut(S):
    id: str
    name: str
    widgets: list[dict[str, Any]]
    sort: int
    updated_at: datetime


class DashIn(S):
    name: str
    widgets: list[dict[str, Any]] = []
    id: str | None = None


class DashPatch(S):
    name: str | Unset = UNSET
    widgets: list[dict[str, Any]] | Unset = UNSET
    sort: int | Unset = UNSET


class SetupIn(S):
    owner: auth.UserIn
    home: HomePatch


async def get_home(s: AsyncSession) -> HomeOut:
    return out(await events.home(s), HomeOut)


async def update_home(s: AsyncSession, p: Principal, data: HomePatch) -> HomeOut:
    p.need("admin")
    h = await events.home(s)
    if not isinstance(data.timezone, Unset) and zone(data.timezone).__class__.__name__ != "ZoneInfo":
        raise ApplicationError("validation", 422, detail="timezone")
    if not isinstance(data.settings, Unset):
        data.settings = {**h.settings, **data.settings}
    patch(h, data)
    await events.add(s, "home.updated", actor=p.actor, params={"name": h.name})
    snap = out(h, HomeOut)
    after(s, lambda: realtime.emit("home", snap, ["all"]))
    return snap


GEOM_MAX = 20000
GEOM_DEVICES = 500


def _num(v: Any, lo: float, hi: float) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and lo <= v <= hi


def clean_geom(g: dict[str, Any]) -> dict[str, Any]:
    """Геометрия помещения на плане: x, y, w, h и доли положения устройств внутри помещения."""
    if not g:
        return {}
    if set(g) - {"x", "y", "w", "h", "devs"}:
        raise ApplicationError("validation", 422, detail="geom")
    if not all(_num(g.get(k), 0, GEOM_MAX) for k in ("x", "y", "w", "h")) or g["w"] <= 0 or g["h"] <= 0:
        raise ApplicationError("validation", 422, detail="geom")
    out = {k: g[k] for k in ("x", "y", "w", "h")}
    devs = g.get("devs")
    if devs is None:
        return out
    if not isinstance(devs, dict) or len(devs) > GEOM_DEVICES:
        raise ApplicationError("validation", 422, detail="geom.devs")
    for key, pos in devs.items():
        ok = isinstance(pos, list) and len(pos) == 2 and all(_num(v, 0, 1) for v in pos)
        if not ok or not key or len(key) > 128:
            raise ApplicationError("validation", 422, detail="geom.devs")
    if devs:
        out["devs"] = {k: [round(float(v), 4) for v in pos] for k, pos in devs.items()}
    return out


async def rooms(s: AsyncSession) -> list[RoomOut]:
    return [out(r, RoomOut) for r in (await s.scalars(select(Room).order_by(Room.floor, Room.sort, Room.name))).all()]


async def create_room(s: AsyncSession, p: Principal, data: RoomIn) -> RoomOut:
    p.need("admin")
    rid = data.id or slug(data.name, "room")
    if await s.get(Room, rid):
        raise ApplicationError("validation", 422, detail="id")
    sort = data.sort or (await s.scalar(select(func.coalesce(func.max(Room.sort), 0))) or 0) + 1
    r = Room(id=rid, name=data.name, floor=data.floor, outdoor=data.outdoor, geom=clean_geom(data.geom), sort=sort)
    s.add(r)
    await s.flush()
    await events.add(s, "room.created", actor=p.actor, params={"name": r.name}, room_id=r.id)
    return _room_changed(s, r)


async def update_room(s: AsyncSession, p: Principal, room_id: str, data: RoomPatch) -> RoomOut:
    p.need("admin")
    r = await s.get(Room, room_id)
    if r is None:
        raise ApplicationError("room_not_found", 404)
    if not isinstance(data.geom, Unset):
        data.geom = clean_geom(data.geom)
    patch(r, data)
    return _room_changed(s, r)


async def delete_room(s: AsyncSession, p: Principal, room_id: str) -> None:
    p.need("admin")
    r = await s.get(Room, room_id)
    if r is None:
        raise ApplicationError("room_not_found", 404)
    await events.add(s, "room.removed", "warn", actor=p.actor, params={"name": r.name})
    await s.delete(r)
    after(s, lambda: realtime.emit("room_gone", {"id": room_id}, ["all"]))


def _room_changed(s: AsyncSession, r: Room) -> RoomOut:
    snap = out(r, RoomOut)
    after(s, lambda: realtime.emit("room", snap, ["all"]))
    return snap


async def dashboards(s: AsyncSession) -> list[DashOut]:
    return [
        out(d, DashOut) for d in (await s.scalars(select(Dashboard).order_by(Dashboard.sort, Dashboard.name))).all()
    ]


async def create_dashboard(s: AsyncSession, p: Principal, data: DashIn) -> DashOut:
    p.need("member")
    did = data.id or slug(data.name, "board")
    if await s.get(Dashboard, did):
        raise ApplicationError("validation", 422, detail="id")
    sort = (await s.scalar(select(func.coalesce(func.max(Dashboard.sort), 0))) or 0) + 1
    d = Dashboard(id=did, name=data.name, widgets=data.widgets, sort=sort)
    s.add(d)
    await s.flush()
    return _dash_changed(s, d)


async def update_dashboard(s: AsyncSession, p: Principal, dash_id: str, data: DashPatch) -> DashOut:
    p.need("member")
    d = await s.get(Dashboard, dash_id)
    if d is None:
        raise ApplicationError("dashboard_not_found", 404)
    patch(d, data)
    return _dash_changed(s, d)


async def delete_dashboard(s: AsyncSession, p: Principal, dash_id: str) -> None:
    p.need("member")
    d = await s.get(Dashboard, dash_id)
    if d is None:
        raise ApplicationError("dashboard_not_found", 404)
    await s.delete(d)
    after(s, lambda: realtime.emit("dashboard_gone", {"id": dash_id}, ["all"]))


def _dash_changed(s: AsyncSession, d: Dashboard) -> DashOut:
    snap = out(d, DashOut)
    after(s, lambda: realtime.emit("dashboard", snap, ["all"]))
    return snap


async def setup_status(s: AsyncSession) -> dict[str, Any]:
    h = await s.get(Home, 1)
    info = await get_json("z2m:info", {}) or {}
    return {
        "done": bool(h and h.setup_done),
        "users": await auth.users_count(s),
        "broker": await alive("mqtt"),
        "zigbee": await kv().get("z2m:state") or "unknown",
        "coordinator": (info.get("coordinator") or {}).get("type"),
        "channel": (info.get("network") or {}).get("channel"),
        "env": environment(),
    }


async def setup_open(s: AsyncSession) -> None:
    """Шаги мастера без входа разрешены, только пока владельца нет."""
    if await auth.users_count(s):
        raise ApplicationError("setup_done", 409)


async def setup(s: AsyncSession, data: SetupIn) -> auth.Session:
    if await auth.users_count(s):
        raise ApplicationError("setup_done", 409)
    if len(data.owner.password) < 6 or not data.owner.username.strip():
        raise ApplicationError("validation", 422, detail="owner")
    u = await auth.ensure_owner(s, data.owner.username, data.owner.name, data.owner.password)
    h = await events.home(s)
    patch(h, data.home)
    h.setup_done = True
    await events.add(s, "home.setup", "ok", actor=f"user:{u.username}", params={"name": h.name})
    return auth.Session(token=auth.make_jwt(str(u.id), "session", auth.SESSION_TTL), user=out(u, auth.UserOut))
