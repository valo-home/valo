import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import after
from app.db.models import Device, Scene
from app.domain import devices, events
from app.domain.common import UNSET, Principal, S, Unset, out, patch, slug
from app.lib import log, realtime
from app.lib.errors import ApplicationError
from app.lib.kv import kv

_log = log.get("scenes")


class SceneOut(S):
    id: str
    name: str
    icon: str
    actions: dict[str, Any]
    sort: int


class SceneIn(S):
    name: str
    icon: str = "layers"
    actions: dict[str, Any] = {}
    sort: int = 0
    id: str | None = None


class ScenePatch(S):
    name: str | Unset = UNSET
    icon: str | Unset = UNSET
    actions: dict[str, Any] | Unset = UNSET
    sort: int | Unset = UNSET


async def get(s: AsyncSession, scene_id: str) -> Scene:
    sc = await s.get(Scene, scene_id)
    if sc is None:
        raise ApplicationError("scene_not_found", 404)
    return sc


async def listing(s: AsyncSession) -> list[SceneOut]:
    return [out(x, SceneOut) for x in (await s.scalars(select(Scene).order_by(Scene.sort, Scene.name))).all()]


async def create(s: AsyncSession, p: Principal, data: SceneIn) -> SceneOut:
    p.need("admin")
    sid = data.id or slug(data.name, "scene")
    if await s.get(Scene, sid):
        sid = f"{sid}-{uuid.uuid4().hex[:4]}"
    sort = data.sort or (await s.scalar(select(func.coalesce(func.max(Scene.sort), 0))) or 0) + 1
    sc = Scene(id=sid, name=data.name, icon=data.icon, actions=data.actions, sort=sort)
    s.add(sc)
    await s.flush()
    await events.add(s, "scene.created", actor=p.actor, params={"name": sc.name})
    return _changed(s, sc)


async def update(s: AsyncSession, p: Principal, scene_id: str, data: ScenePatch) -> SceneOut:
    p.need("admin")
    sc = await get(s, scene_id)
    patch(sc, data)
    return _changed(s, sc)


async def remove(s: AsyncSession, p: Principal, scene_id: str) -> None:
    p.need("admin")
    sc = await get(s, scene_id)
    await events.add(s, "scene.removed", "warn", actor=p.actor, params={"name": sc.name})
    await s.delete(sc)
    after(s, lambda: realtime.emit("scene_gone", {"id": scene_id}, ["all"]))


def _changed(s: AsyncSession, sc: Scene) -> SceneOut:
    snap = out(sc, SceneOut)
    after(s, lambda: realtime.emit("scene", snap, ["all"]))
    return snap


async def apply(
    s: AsyncSession, p: Principal, scene_id: str, actor: str | None = None, cause_id: int | None = None
) -> dict[str, Any]:
    sc = await get(s, scene_id)
    p.need("member")
    group = uuid.uuid4().hex[:16]
    ev = await events.add(
        s,
        "scene.applied",
        actor=actor or p.actor,
        params={"name": sc.name, "count": len(sc.actions)},
        cause_id=cause_id,
    )
    sent, skipped = [], []
    for did, values in sc.actions.items():
        d = await s.get(Device, did)
        ok = d is not None and p.room_ok(d.room_id) and isinstance(values, dict) and bool(values)
        (sent if ok else skipped).append(did)
    if sent:
        mapping = {
            "total": len(sent),
            "done": 0,
            "scene": sc.id,
            "name": sc.name,
            "actor": actor or p.actor,
            "cause": ev.id,
        }
        after(s, lambda: kv().hset(f"grp:{group}", mapping=mapping))
    for did in sent:
        await devices.command(s, p, did, sc.actions[did], actor=actor or p.actor, cause_id=ev.id, group=group)
    _log.info("scene_apply", scene=sc.id, sent=len(sent), skipped=skipped, group=group)
    return {"group": group, "sent": sent, "skipped": skipped, "eventId": ev.id}


async def done(s: AsyncSession, name: str, actor: str, total: int, failed: list[str], cause: int | None) -> None:
    if failed:
        await events.add(
            s,
            "scene.partial",
            "crit",
            actor=actor,
            params={"name": name, "ok": total - len(failed), "total": total, "failed": failed},
            cause_id=cause,
        )
    else:
        await events.add(s, "scene.done", "ok", actor=actor, params={"name": name, "total": total}, cause_id=cause)


async def capture(s: AsyncSession, p: Principal, scene_id: str) -> SceneOut:
    p.need("admin")
    sc = await get(s, scene_id)
    actions = {}
    for did, values in sc.actions.items():
        d = await s.get(Device, did)
        if d is None or not isinstance(values, dict):
            continue
        writable = {c["id"] for c in d.caps if "w" in c.get("access", "")}
        actions[did] = {k: d.state.get(k) for k in values if k in writable and d.state.get(k) is not None}
    sc.actions = actions
    await events.add(s, "scene.captured", actor=p.actor, params={"name": sc.name})
    return _changed(s, sc)
