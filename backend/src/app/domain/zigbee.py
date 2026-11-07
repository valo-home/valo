import time
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import after
from app.db.models import Device
from app.domain import devices, events
from app.domain.common import Principal
from app.lib import log, mqtt, realtime, tasks
from app.lib.errors import ApplicationError
from app.lib.kv import get_json, kv, set_json
from app.lib.settings import settings

_log = log.get("zigbee")


async def request(path: str, payload: dict[str, Any], timeout: float = 10.0) -> Any:
    if await kv().get("z2m:state") == "offline":
        raise ApplicationError("z2m_offline", 503)
    tx = uuid.uuid4().hex[:12]
    res = await mqtt.request(f"{settings.z2m_topic}/bridge/request/{path}", {**payload, "transaction": tx}, tx, timeout)
    if not isinstance(res, dict) or res.get("status") != "ok":
        raise ApplicationError(
            "z2m_error", 502, detail=str((res or {}).get("error") if isinstance(res, dict) else res)[:200]
        )
    return res.get("data")


async def zdev(s: AsyncSession, device_id: str) -> Device:
    d = await devices.get(s, device_id)
    if d.source != "zigbee":
        raise ApplicationError("not_zigbee", 422)
    return d


async def info(s: AsyncSession) -> dict[str, Any]:
    raw = await get_json("z2m:info", {}) or {}
    coord = await get_json("z2m:coordinator", {}) or {}
    ds = (await s.scalars(select(Device).where(Device.source == "zigbee"))).all()
    net = raw.get("network") or {}
    return {
        "state": await kv().get("z2m:state") or "unknown",
        "version": raw.get("version"),
        "coordinator": {
            **(raw.get("coordinator") or {}),
            "ieee": coord.get("ieee_address"),
            "model": (coord.get("definition") or {}).get("model"),
        },
        "network": {
            "channel": net.get("channel"),
            "panId": net.get("pan_id"),
            "extendedPanId": net.get("extended_pan_id"),
        },
        "permitJoin": raw.get("permit_join", False),
        "permitJoinEnd": raw.get("permit_join_end"),
        "counts": {
            "devices": len(ds),
            "routers": sum(1 for d in ds if d.attrs.get("type") == "Router"),
            "weak": sum(1 for d in ds if isinstance(d.attrs.get("lqi"), (int, float)) and d.attrs["lqi"] < 60),
            "offline": sum(1 for d in ds if not d.available),
            "ota": sum(1 for d in ds if (d.attrs.get("ota") or {}).get("state") == "available"),
        },
        "config": {k: (raw.get("config") or {}).get(k) for k in ("serial", "advanced", "availability", "ota")},
    }


async def health(s: AsyncSession) -> list[dict[str, Any]]:
    rows = []
    for d in (await s.scalars(select(Device).where(Device.source == "zigbee").order_by(Device.name))).all():
        rows.append(
            {
                "id": d.id,
                "name": d.name,
                "roomId": d.room_id,
                "type": d.attrs.get("type"),
                "power": d.attrs.get("power"),
                "lqi": d.attrs.get("lqi"),
                "battery": d.state.get("bat"),
                "available": d.available,
                "lastSeen": d.last_seen.isoformat() if d.last_seen else None,
                "model": d.model,
                "ota": d.attrs.get("ota"),
                "sw": d.attrs.get("sw"),
                "nwk": d.attrs.get("nwk"),
            }
        )
    return rows


async def permit_join(s: AsyncSession, p: Principal, seconds: int, via: str | None) -> dict[str, Any]:
    p.need("admin")
    payload: dict[str, Any] = {"time": max(0, min(int(seconds), 254))}
    name = None
    if via:
        d = await zdev(s, via)
        payload["device"], name = d.address, d.name
    await request("permit_join", payload)
    await events.add(
        s,
        "zigbee.permit_join" if payload["time"] else "zigbee.permit_join_off",
        actor=p.actor,
        params={"time": payload["time"], "via": name},
    )
    return {"time": payload["time"], "until": time.time() + payload["time"]}


async def networkmap_start(p: Principal) -> None:
    p.need("admin")
    if await kv().set("z2m:networkmap:busy", "1", nx=True, ex=180):
        await tasks.kick("zigbee.networkmap")


async def networkmap_run() -> None:
    try:
        data = await request("networkmap", {"type": "raw", "routes": False}, timeout=150)
        await set_json("z2m:networkmap", {"ts": time.time(), "data": data})
        await realtime.emit("zigbee", {"type": "networkmap", "ok": True}, ["zigbee"])
    except ApplicationError as e:
        _log.warning("networkmap_failed", code=e.code)
        await realtime.emit("zigbee", {"type": "networkmap", "ok": False, "code": e.code}, ["zigbee"])
    finally:
        await kv().delete("z2m:networkmap:busy")


async def networkmap() -> dict[str, Any]:
    return await get_json("z2m:networkmap", {}) or {}


def _ota_ready(d: Device) -> None:
    if d.attrs.get("otaSupported") is False:
        raise ApplicationError("ota_unsupported", 422, name=d.name)


async def ota_check(s: AsyncSession, p: Principal, device_id: str) -> Any:
    p.need("admin")
    d = await zdev(s, device_id)
    _ota_ready(d)
    return await request("device/ota_update/check", {"id": d.address}, 90)


async def ota_update(s: AsyncSession, p: Principal, device_id: str) -> None:
    p.need("admin")
    d = await zdev(s, device_id)
    _ota_ready(d)
    await events.add(s, "zigbee.ota_started", actor=p.actor, params={"name": d.name}, device_id=d.id, room_id=d.room_id)
    addr, did = d.address, d.id
    after(s, lambda: tasks.kick("zigbee.ota", address=addr, device=did))


async def ota_run(s: AsyncSession, address: str, device_id: str) -> None:
    d = await s.get(Device, device_id)
    try:
        data = await request("device/ota_update/update", {"id": address}, 3600)
        await events.add(
            s,
            "zigbee.ota_done",
            "ok",
            params={"name": d.name if d else address, "to": (data or {}).get("to")},
            device_id=device_id,
        )
    except ApplicationError as e:
        await events.add(
            s,
            "zigbee.ota_failed",
            "crit",
            params={"name": d.name if d else address, "code": e.code, **e.params},
            device_id=device_id,
        )


async def device_action(s: AsyncSession, p: Principal, device_id: str, action: str) -> Any:
    p.need("admin")
    if action not in ("configure", "interview"):
        raise ApplicationError("not_found", 404)
    d = await zdev(s, device_id)
    await events.add(s, f"zigbee.{action}", actor=p.actor, params={"name": d.name}, device_id=d.id, room_id=d.room_id)
    return await request(f"device/{action}", {"id": d.address}, 90)


async def backup() -> str:
    data = await request("backup", {}, 90)
    return (data or {}).get("zip", "")


async def set_channel(s: AsyncSession, p: Principal, channel: int) -> dict[str, Any]:
    p.need("owner")
    if not 11 <= channel <= 26:
        raise ApplicationError("validation", 422, detail="channel")
    data = await request("options", {"options": {"advanced": {"channel": channel}}}, 20)
    await events.add(s, "zigbee.channel", "warn", actor=p.actor, params={"channel": channel})
    return {"restartRequired": bool((data or {}).get("restart_required", True))}


async def converter(name: str, code: str | None) -> None:
    if code is None:
        await request("converter/remove", {"name": name}, 20)
    else:
        await request("converter/save", {"name": name, "code": code}, 20)
