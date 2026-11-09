import json
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import after
from app.db.models import Device, Extension
from app.domain import adapters, devices, events, zigbee
from app.domain.common import slug
from app.lib import log, realtime
from app.lib.kv import kv, set_json
from app.lib.security import digest
from app.lib.settings import settings

_log = log.get("ingest")
_HUB = re.compile(r"^hub/v1/(?:dev/([^/]+)|ext/([^/]+)/dev/([^/]+))/(meta|state|avail|ack|event)$")


def _state(payload: Any) -> str:
    return payload.get("state", "") if isinstance(payload, dict) else str(payload or "")


async def z2m(s: AsyncSession, sub: str, payload: Any) -> None:
    if sub == "bridge/state":
        st = _state(payload)
        prev = await kv().getset("z2m:state", st)
        if prev != st:
            await zigbee.bridge_state(s, st)
            after(s, lambda: realtime.emit("zigbee", {"type": "state", "state": st}, ["zigbee", "all"]))
    elif sub == "bridge/info":
        await set_json("z2m:info", payload)
        after(s, lambda: realtime.emit("zigbee", {"type": "info"}, ["zigbee"]))
    elif sub == "bridge/devices" and isinstance(payload, list):
        await z2m_devices(s, payload)
    elif sub == "bridge/event" and isinstance(payload, dict):
        await z2m_event(s, payload)
    elif sub.startswith("bridge/"):
        return
    elif sub.endswith("/availability"):
        d = await z2m_device(s, sub.rsplit("/", 1)[0])
        if d:
            await devices.set_available(s, d, _state(payload) == "online")
    elif "/" not in sub or sub.rsplit("/", 1)[1] not in ("set", "get"):
        d = await z2m_device(s, sub)
        if d and isinstance(payload, dict):
            ota = payload.get("update")
            if isinstance(ota, dict) and ota != d.attrs.get("ota"):
                d.attrs = {**d.attrs, "ota": ota}
                data = {"type": "ota", "device": d.id, "ota": ota}
                after(s, lambda: realtime.emit("zigbee", data, ["zigbee", f"dev:{d.id}"]))
            if "linkquality" in payload:
                d.attrs = {**d.attrs, "lqi": payload["linkquality"]}
            await devices.apply(s, d, adapters.z2m_in(d.attrs.get("conv") or {}, payload))


async def z2m_device(s: AsyncSession, name: str) -> Device | None:
    ieee = await kv().hget("z2m:names", name)
    if ieee:
        return await s.get(Device, ieee)
    return await s.scalar(select(Device).where(Device.source == "zigbee", Device.address == name))


async def z2m_devices(s: AsyncSession, items: list[dict[str, Any]]) -> None:
    seen, names = set(), {}
    for it in items:
        if it.get("type") == "Coordinator":
            await set_json("z2m:coordinator", it)
            continue
        ieee = it.get("ieee_address")
        if not ieee:
            continue
        seen.add(ieee)
        names[it.get("friendly_name") or ieee] = ieee
        try:
            async with s.begin_nested():
                await _z2m_item(s, ieee, it)
        except Exception as e:
            _log.error("z2m_device_failed", ieee=ieee, model=it.get("model_id"), error=str(e)[:300])
    pipe = kv().pipeline()
    pipe.delete("z2m:names")
    if names:
        pipe.hset("z2m:names", mapping=names)
    await pipe.execute()
    for d in (await s.scalars(select(Device).where(Device.source == "zigbee"))).all():
        if d.id not in seen:
            await events.add(
                s,
                "device.removed",
                "warn",
                params={"name": d.name, "source": "zigbee"},
                device_id=d.id,
                room_id=d.room_id,
            )
            gone = {"id": d.id}
            rooms = devices.rooms_of(d)
            await s.delete(d)
            after(s, lambda gone=gone, rooms=rooms: realtime.emit("device_gone", gone, rooms))


async def _z2m_item(s: AsyncSession, ieee: str, it: dict[str, Any]) -> None:
    definition = it.get("definition") or {}
    caps, conv = adapters.z2m_caps(definition.get("exposes") or [])
    model = " ".join(x for x in (definition.get("vendor"), definition.get("model")) if x) or it.get("model_id") or ""
    current = await s.get(Device, ieee)
    attrs = {
        "conv": conv,
        "type": it.get("type"),
        "nwk": it.get("network_address"),
        "power": it.get("power_source"),
        "modelId": it.get("model_id"),
        "description": definition.get("description"),
        "sw": it.get("software_build_id"),
        "supported": it.get("supported", bool(definition)),
        "interviewed": it["interview_state"] == "SUCCESSFUL"
        if "interview_state" in it
        else it.get("interview_completed", True),
        "interview": it.get("interview_state"),
        "otaSupported": bool(definition.get("supports_ota")) if definition else None,
    }
    fallback = definition.get("description") or it.get("friendly_name") or ieee
    renamed = current is not None and current.name not in (ieee, it.get("friendly_name"))
    name = current.name if renamed and current else fallback
    if current is not None and not renamed and current.name != fallback:
        current.name = fallback
    await devices.upsert(
        s,
        ieee,
        "zigbee",
        name,
        ieee=ieee,
        address=it.get("friendly_name") or ieee,
        model=model,
        vendor=definition.get("vendor") or "",
        caps=caps,
        kind=adapters.kind_of(caps),
        attrs=attrs,
    )


async def z2m_event(s: AsyncSession, msg: dict[str, Any]) -> None:
    kind, data = msg.get("type", ""), msg.get("data") or {}
    ieee = data.get("ieee_address")
    if kind == "device_interview":
        status = data.get("status")
        level = {"successful": "ok", "failed": "crit"}.get(status, "info")
        model = (data.get("definition") or {}).get("model")
        await events.add(
            s,
            f"zigbee.interview_{status}",
            level,
            params={"ieee": ieee, "name": data.get("friendly_name"), "model": model},
            device_id=ieee if status == "successful" else None,
        )
    elif kind in ("device_joined", "device_leave"):
        await events.add(
            s,
            f"zigbee.{kind}",
            "info" if kind == "device_joined" else "warn",
            params={"ieee": ieee, "name": data.get("friendly_name")},
        )
        if kind == "device_leave" and ieee and (d := await s.get(Device, ieee)):
            await devices.set_available(s, d, False)
    payload = {"type": "pairing", "event": kind, "data": data}
    after(s, lambda: realtime.emit("zigbee", payload, ["zigbee"]))


async def ha_config(s: AsyncSession, topic: str, payload: Any) -> None:
    sign = digest(json.dumps(payload, sort_keys=True)) if isinstance(payload, dict) and payload else ""
    owner = await kv().hget("ha:configs", topic)
    if sign and owner and await kv().hget("ha:hash", topic) == sign:
        return
    if owner:
        d = await s.get(Device, owner)
        if d:
            await _ha_drop(s, d, topic, keep=bool(sign))
    if not sign:
        await kv().hdel("ha:configs", topic)
        await kv().hdel("ha:hash", topic)
        after(s, lambda: kv().publish("mqtt:index", "1"))
        return
    for platform, oid, c in adapters.ha_components(topic, payload):
        if str(c.get("state_topic") or "").startswith(f"{settings.z2m_topic}/"):
            continue
        dev = c.get("device") or {}
        ident = dev.get("identifiers") or c.get("unique_id") or oid
        ident = ident[0] if isinstance(ident, list) and ident else ident
        did = f"ha-{slug(str(ident), 'ha')}"
        d = await s.get(Device, did)
        caps = list(d.caps) if d else []
        conv = dict((d.attrs.get("conv") or {}) if d else {})
        cmps = dict((d.attrs.get("cmps") or {}) if d else {})
        got = adapters.ha_cap(platform, oid, c, {x["id"] for x in caps})
        if not got:
            continue
        cap, cv = got
        caps = [x for x in caps if x["id"] != cap["id"]] + [cap]
        conv[cap["id"]] = cv
        cmps.setdefault(topic, [])
        if cap["id"] not in cmps[topic]:
            cmps[topic].append(cap["id"])
        model = " ".join(x for x in (dev.get("manufacturer"), dev.get("model")) if x) or (c.get("origin") or {}).get(
            "name", ""
        )
        attrs = {
            "conv": conv,
            "cmps": cmps,
            "configs": sorted(cmps),
            "origin": (payload.get("origin") or payload.get("o") or {}).get("name")
            if isinstance(payload.get("origin") or payload.get("o"), dict)
            else None,
        }
        await devices.upsert(
            s,
            did,
            "ha",
            d.name if d else dev.get("name") or c.get("name") or oid,
            address=str(ident),
            model=model,
            vendor=dev.get("manufacturer") or "",
            caps=caps,
            kind=adapters.kind_of(caps),
            attrs=attrs,
        )
        await kv().hset("ha:configs", topic, did)
    await kv().hset("ha:hash", topic, sign)
    after(s, lambda: kv().publish("mqtt:index", "1"))


async def _ha_drop(s: AsyncSession, d: Device, topic: str, keep: bool = False) -> None:
    cmps = dict(d.attrs.get("cmps") or {})
    drop = set(cmps.pop(topic, []))
    if not cmps and not keep:
        await events.add(
            s, "device.removed", "warn", params={"name": d.name, "source": "ha"}, device_id=d.id, room_id=d.room_id
        )
        gone, rooms = {"id": d.id}, devices.rooms_of(d)
        await s.delete(d)
        await s.flush()
        after(s, lambda: realtime.emit("device_gone", gone, rooms))
        return
    d.caps = [c for c in d.caps if c["id"] not in drop]
    d.attrs = {
        **d.attrs,
        "cmps": cmps,
        "configs": sorted(cmps),
        "conv": {k: v for k, v in (d.attrs.get("conv") or {}).items() if k not in drop},
    }


async def mapped(s: AsyncSession, topic: str, payload: Any, targets: list[list[str]]) -> None:
    for did, kind in targets:
        d = await s.get(Device, did)
        if d is None:
            continue
        if kind == "avail":
            conv = next((c for c in (d.attrs.get("conv") or {}).values() if c.get("avail") == topic), None)
            if conv:
                await devices.set_available(s, d, str(payload) == str(conv.get("aon")))
        elif kind == "ha":
            await devices.apply(s, d, adapters.ha_in(d.caps, d.attrs.get("conv") or {}, topic, payload))
        elif kind == "map":
            await devices.apply(s, d, adapters.map_in(d.attrs.get("map") or [], topic, payload))


async def hub(s: AsyncSession, topic: str, payload: Any) -> bool:
    m = _HUB.match(topic)
    if not m:
        return False
    dev_id, ext, ext_dev, part = m.groups()
    did = slug(dev_id or f"{ext.rsplit('.', 1)[-1]}-{ext_dev}", "dev")
    source, address = ("mqtt", dev_id) if dev_id else ("ext", ext_dev)
    if part == "meta":
        if not isinstance(payload, dict) or not payload:
            d = await s.get(Device, did)
            if d and (not ext or d.ext_id == ext):
                await events.add(
                    s,
                    "device.removed",
                    "warn",
                    params={"name": d.name, "source": source},
                    device_id=d.id,
                    room_id=d.room_id,
                )
                gone, rooms = {"id": d.id}, devices.rooms_of(d)
                await s.delete(d)
                after(s, lambda: realtime.emit("device_gone", gone, rooms))
            return True
        if ext and await s.get(Extension, ext) is None:
            _log.warning("ext_device_ignored", ext=ext, device=ext_dev, reason="extension not installed")
            return True
        caps = adapters.hub_caps(payload)
        cur = await s.get(Device, did)
        if ext and cur is not None and cur.ext_id != ext:
            _log.warning("ext_device_foreign", ext=ext, device=did, owner=cur.ext_id)
            return True
        await devices.upsert(
            s,
            did,
            source,
            str(payload.get("name") or (cur.name if cur else did))[:120],
            address=address,
            ext_id=ext,
            model=str(payload.get("model") or ""),
            vendor=str(payload.get("vendor") or ""),
            caps=caps,
            kind=adapters.kind_of(caps, payload.get("kind")),
            attrs={"meta": {k: v for k, v in payload.items() if k not in ("caps",)}},
        )
        return True
    d = await s.get(Device, did)
    if d is None:
        return True
    if ext and d.ext_id != ext:
        _log.warning("ext_device_foreign", ext=ext, device=did, owner=d.ext_id)
        return True
    if part == "state" and isinstance(payload, dict):
        await devices.apply(s, d, {k: v for k, v in payload.items() if not k.startswith("_")})
        if "_attrs" in payload and isinstance(payload["_attrs"], dict):
            d.attrs = {**d.attrs, "data": payload["_attrs"]}
    elif part == "avail":
        await devices.set_available(s, d, _state(payload) == "online")
    elif part == "ack" and isinstance(payload, dict):
        await devices.ack(s, d, payload)
    elif part == "event":
        action = payload.get("action") if isinstance(payload, dict) else payload
        if action:
            await devices.apply(s, d, {"action": action})
    return True


async def broker_stats(topic: str, payload: Any) -> None:
    key = topic.removeprefix("$SYS/broker/")
    if key in (
        "version",
        "uptime",
        "clients/connected",
        "clients/total",
        "messages/received",
        "messages/sent",
        "retained messages/count",
        "load/messages/received/1min",
        "load/messages/sent/1min",
        "subscriptions/count",
    ):
        await kv().hset("mqtt:sys", key, str(payload))


def clean(v: Any) -> Any:
    if isinstance(v, str):
        return v.replace("\x00", "").strip() if "\x00" in v else v
    if isinstance(v, dict):
        return {clean(k): clean(x) for k, x in v.items()}
    if isinstance(v, list):
        return [clean(x) for x in v]
    return v


def parse(raw: bytes | bytearray | str) -> Any:
    text = raw.decode(errors="replace") if isinstance(raw, (bytes, bytearray)) else raw
    if not text:
        return ""
    try:
        return clean(json.loads(text))
    except ValueError:
        return clean(text)


def base() -> str:
    return settings.z2m_topic
