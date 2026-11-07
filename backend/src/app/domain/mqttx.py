import json
import time
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import now
from app.db.models import Device
from app.domain import events
from app.domain.common import Principal, S, slug
from app.lib import log, mqtt, realtime
from app.lib.errors import ApplicationError
from app.lib.kv import kv
from app.lib.security import digest, new_secret

DYNSEC = "$CONTROL/dynamic-security/v1"
_log = log.get("mqttx")


class PublishIn(S):
    topic: str
    payload: str = ""
    qos: int = 0
    retain: bool = False


class AccountIn(S):
    device_id: str


async def broker() -> dict[str, Any]:
    sys = await kv().hgetall("mqtt:sys")
    return {"sys": sys, "topics": await kv().hlen("mqtt:topics"), "connected": await kv().exists("beat:mqtt") == 1}


async def record(t: str, text: str, retain: bool, qos: int) -> None:
    ts = time.time()
    if retain and not text:
        await kv().hdel("mqtt:topics", t)
        await realtime.emit("mqtt", {"t": t, "gone": True, "ts": ts}, ["mqtt"], durable=False)
        return
    prev = await kv().hget("mqtt:topics", t)
    old = json.loads(prev) if prev else {}
    hist = [[old["ts"], old["p"]], *old.get("h", [])][:5] if old else []
    body = text if len(text) <= 4096 else text[:4096] + "..."
    row = {"p": body, "r": retain, "q": qos, "ts": ts, "n": old.get("n", 0) + 1, "h": hist}
    pipe = kv().pipeline()
    pipe.hset("mqtt:topics", t, json.dumps(row))
    pipe.lpush("mqtt:log", json.dumps([ts, t, body[:300], retain]))
    pipe.ltrim("mqtt:log", 0, 199)
    await pipe.execute()
    await realtime.emit("mqtt", {"t": t, "p": body[:300], "r": retain, "q": qos, "ts": ts}, ["mqtt"], durable=False)


async def topics() -> list[dict[str, Any]]:
    rows = []
    for t, raw in (await kv().hgetall("mqtt:topics")).items():
        v = json.loads(raw)
        rows.append({"t": t, "p": v["p"][:160], "r": v["r"], "q": v["q"], "ts": v["ts"], "n": v.get("n", 1)})
    return sorted(rows, key=lambda r: r["t"])


async def topic(t: str) -> dict[str, Any]:
    raw = await kv().hget("mqtt:topics", t)
    if not raw:
        raise ApplicationError("not_found", 404)
    return {"t": t, **json.loads(raw)}


async def recent(limit: int = 100) -> list[list[Any]]:
    return [json.loads(x) for x in await kv().lrange("mqtt:log", 0, limit - 1)]


async def publish(s: AsyncSession, p: Principal, data: PublishIn) -> None:
    p.need("admin")
    if not data.topic or "+" in data.topic or "#" in data.topic or data.topic.startswith("$") or len(data.topic) > 512:
        raise ApplicationError("topic_invalid", 422)
    await mqtt.publish(data.topic, data.payload, qos=max(0, min(data.qos, 2)), retain=data.retain)
    await events.add(s, "mqtt.published", actor=p.actor, params={"topic": data.topic, "retain": data.retain})


async def discovery(s: AsyncSession) -> list[dict[str, Any]]:
    rows = []
    owners = await kv().hgetall("ha:configs")
    by_dev: dict[str, list[str]] = {}
    for t, did in owners.items():
        by_dev.setdefault(did, []).append(t)
    stale = now() - timedelta(minutes=10)
    for d in (await s.scalars(select(Device).where(Device.source == "ha"))).all():
        ghost = (d.last_seen is None and d.created_at < stale) or not d.available
        rows.append(
            {
                "device": d.id,
                "name": d.name,
                "origin": d.attrs.get("origin"),
                "configs": sorted(by_dev.get(d.id, d.attrs.get("configs", []))),
                "lastSeen": d.last_seen,
                "available": d.available,
                "ghost": ghost,
                "caps": len(d.caps),
            }
        )
    return rows


async def drop_config(s: AsyncSession, p: Principal, t: str) -> None:
    p.need("admin")
    if not t.startswith("homeassistant/") or not t.endswith("/config"):
        raise ApplicationError("topic_invalid", 422)
    await mqtt.publish(t, "", qos=1, retain=True)
    await events.add(s, "mqtt.config_removed", "warn", actor=p.actor, params={"topic": t})


async def dynsec(*commands: dict[str, Any], timeout: float = 5.0) -> list[dict[str, Any]]:
    corr = uuid.uuid4().hex
    cmds = [{**c, "correlationData": f"{corr}:{i}"} for i, c in enumerate(commands)]
    res = await mqtt.request(DYNSEC, {"commands": cmds}, corr, timeout)
    return res.get("responses", []) if isinstance(res, dict) else []


async def clients() -> dict[str, Any]:
    res = await dynsec({"command": "listClients", "verbose": True}, {"command": "listRoles", "verbose": True})
    data = {r.get("command"): r.get("data") or {} for r in res}
    return {
        "clients": (data.get("listClients") or {}).get("clients", []),
        "roles": (data.get("listRoles") or {}).get("roles", []),
    }


def _acl(kind: str, topic: str) -> dict[str, Any]:
    return {"acltype": kind, "topic": topic, "allow": True, "priority": 0}


async def ensure(username: str, password: str, role: str, acls: list[dict[str, Any]], reset: bool = True) -> None:
    mark, sign = f"mqtt:acct:{username}", digest(f"{password}:{json.dumps(acls, sort_keys=True)}")
    if not reset and await kv().get(mark) == sign:
        return
    drop = [{"command": "deleteClient", "username": username}] if reset else []
    res = await dynsec(
        *drop,
        {"command": "deleteRole", "rolename": role},
        {"command": "createRole", "rolename": role, "acls": acls},
        {"command": "createClient", "username": username, "password": password, "roles": [{"rolename": role}]},
        {"command": "addClientRole", "username": username, "rolename": role},
        {"command": "setClientPassword", "username": username, "password": password},
    )
    errors = [r for r in res if r.get("error") and r.get("command") == "setClientPassword"]
    if errors or not res:
        _log.error("dynsec_failed", username=username, errors=errors)
        raise ApplicationError("mqtt_unavailable", 502)
    await kv().set(mark, sign)


async def drop(username: str, role: str) -> None:
    await dynsec({"command": "deleteClient", "username": username}, {"command": "deleteRole", "rolename": role})


def full_acl(*prefixes: str) -> list[dict[str, Any]]:
    acls = []
    for pfx in prefixes:
        acls += [
            _acl("publishClientSend", pfx),
            _acl("publishClientReceive", pfx),
            _acl("subscribePattern", pfx),
            _acl("unsubscribePattern", pfx),
        ]
    return acls


async def account(s: AsyncSession, p: Principal, device_id: str) -> dict[str, Any]:
    p.need("admin")
    did = slug(device_id, "dev")
    user, pw = f"dev-{did}", new_secret(18)
    await ensure(user, pw, f"dev-{did}", full_acl(f"hub/v1/dev/{did}/#"))
    await events.add(s, "mqtt.account", actor=p.actor, params={"username": user, "device": did})
    return {"username": user, "password": pw, "base": f"hub/v1/dev/{did}", "issued": time.time()}


async def ext_account(ext_id: str, grants: list[str]) -> tuple[str, str]:
    user, pw = f"ext-{ext_id}", new_secret(18)
    acls = [*full_acl(f"hub/v1/ext/{ext_id}/#"), _acl("publishClientSend", mqtt.RESP_TOPIC)]
    if "devices.read" in grants:
        acls += [_acl("subscribePattern", "hub/v1/core/state/#"), _acl("publishClientReceive", "hub/v1/core/state/#")]
    for g in grants:
        if g.startswith("mqtt.publish:"):
            acls.append(_acl("publishClientSend", g.split(":", 1)[1]))
    await ensure(user, pw, f"ext-{ext_id}", acls)
    return user, pw
