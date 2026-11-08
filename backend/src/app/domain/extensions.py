import base64
import json
import pathlib
import uuid
from datetime import datetime
from functools import cache
from typing import Any

import msgspec
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import after, now
from app.db.models import Device, Extension
from app.domain import events
from app.domain.blocks import BlockDef
from app.domain.common import Principal, S, out
from app.lib import log, mqtt, realtime, rtc, secretbox, tasks
from app.lib.errors import ApplicationError, notice
from app.lib.kv import get_json, kv
from app.lib.settings import env

CATALOG = pathlib.Path(env("EXT_CATALOG", "/app/extensions/catalog.json"))
EXT_DIR = pathlib.Path(env("EXT_DIR", "/data/extensions"))
_log = log.get("extensions")
_IO = {
    "trig": ([], ["ev"]),
    "cond": (["ev"], ["ev", "ev"]),
    "act": (["ev"], ["ev"]),
    "logic": (["ev"], ["ev"]),
    "xf": (["ev"], ["n"]),
}


class ExtOut(S):
    id: str
    name: str
    version: str
    trust: str
    status: str
    enabled: bool
    manifest: dict[str, Any]
    settings: dict[str, Any]
    grants: list[str]
    error: str | None
    restarts: int
    pid: int | None
    started_at: datetime | None
    update: str | None = None
    proc: dict[str, Any] | None = None
    secrets: list[str] = []
    new_perms: list[str] = []


class InstallIn(S):
    grants: list[str] = []
    version: str | None = None


class SettingsIn(S):
    values: dict[str, Any]


def _ver(v: str) -> tuple[int, ...]:
    return tuple(int(x) if x.isdigit() else 0 for x in v.split("-")[0].split("."))


@cache
def _catalog_raw(mtime: float) -> list[dict[str, Any]]:
    items = []
    for entry in json.loads(CATALOG.read_text("utf-8")):
        src = (CATALOG.parent / entry["source"]).resolve()
        try:
            manifest = json.loads((src / "manifest.json").read_text("utf-8"))
        except OSError as e:
            _log.error("catalog_manifest_failed", source=str(src), error=str(e))
            continue
        items.append({**entry, "path": str(src), "manifest": manifest})
    return items


def catalog_entries() -> list[dict[str, Any]]:
    try:
        return _catalog_raw(CATALOG.stat().st_mtime)
    except OSError as e:
        _log.warning("catalog_unavailable", path=str(CATALOG), error=str(e))
        return []


def entry(ext_id: str) -> dict[str, Any] | None:
    return next((e for e in catalog_entries() if e["manifest"]["id"] == ext_id), None)


def docs(ext_id: str, lang: str) -> dict[str, Any]:
    e = entry(ext_id)
    if e is None:
        raise ApplicationError("ext_not_found", 404)
    base = pathlib.Path(e["path"]) / "docs"
    for code in (lang, "en", "uk", "ru"):
        f = base / f"{code}.md"
        if f.is_file():
            return {"lang": code, "text": f.read_text("utf-8")}
    return {"lang": lang, "text": ""}


def source_for(ext_id: str, version: str) -> tuple[pathlib.Path, dict[str, Any]] | None:
    e = entry(ext_id)
    if e is None:
        return None
    if e["manifest"]["version"] == version:
        return pathlib.Path(e["path"]), e["manifest"]
    rel = (e.get("older") or {}).get(version)
    if not rel:
        return None
    path = (CATALOG.parent / rel).resolve()
    try:
        return path, json.loads((path / "manifest.json").read_text("utf-8"))
    except OSError:
        return None


def secret_keys(x: Extension) -> set[str]:
    return {st["key"] for st in x.manifest.get("settings", []) if st.get("type") == "secret" and "key" in st}


def plain_settings(x: Extension) -> dict[str, Any]:
    keys = secret_keys(x)
    return {k: (secretbox.open_(v) if k in keys else v) for k, v in (x.settings or {}).items()}


async def _view(x: Extension) -> ExtOut:
    o = out(x, ExtOut)
    keys = secret_keys(x)
    o.secrets = sorted(k for k in keys if (x.settings or {}).get(k))
    o.settings = {k: ("" if k in keys else v) for k, v in (x.settings or {}).items()}
    e = entry(x.id)
    if e and _ver(e["manifest"]["version"]) > _ver(x.version):
        o.update = e["manifest"]["version"]
    o.proc = await get_json(f"ext:proc:{x.id}")
    o.new_perms = new_perms(x) if o.update else []
    return o


async def get(s: AsyncSession, ext_id: str) -> Extension:
    x = await s.get(Extension, ext_id)
    if x is None:
        raise ApplicationError("ext_not_found", 404)
    return x


async def listing(s: AsyncSession) -> list[ExtOut]:
    return [await _view(x) for x in (await s.scalars(select(Extension).order_by(Extension.name))).all()]


async def one(s: AsyncSession, ext_id: str) -> ExtOut:
    return await _view(await get(s, ext_id))


async def catalog(s: AsyncSession) -> list[dict[str, Any]]:
    installed = {x.id: x for x in (await s.scalars(select(Extension))).all()}
    res = []
    for e in catalog_entries():
        m = e["manifest"]
        x = installed.get(m["id"])
        res.append(
            {
                "id": m["id"],
                "manifest": m,
                "downloads": e.get("downloads"),
                "installed": x.version if x else None,
                "status": x.status if x else None,
            }
        )
    return res


async def _cmd(op: str, ext_id: str, **extra: Any) -> None:
    await kv().publish("ext:cmd", json.dumps({"op": op, "id": ext_id, **extra}))


def _changed(s: AsyncSession, x: Extension) -> None:
    async def push() -> None:
        await realtime.emit("ext", await _view(x), ["all"])
        await tasks.kick("flows.reindex")

    after(s, push)


async def install(s: AsyncSession, p: Principal, ext_id: str, data: InstallIn) -> ExtOut:
    p.need("admin")
    e = entry(ext_id)
    if e is None:
        raise ApplicationError("ext_not_found", 404)
    if await s.get(Extension, ext_id):
        raise ApplicationError("ext_installed", 409)
    src = source_for(ext_id, data.version or e["manifest"]["version"])
    if src is None:
        raise ApplicationError("ext_not_found", 404)
    m = src[1]
    missing = [x for x in m.get("perms", []) if x not in data.grants]
    if missing:
        raise ApplicationError("ext_grants", 422, perms=", ".join(missing))
    defaults = {st["key"]: st.get("default") for st in m.get("settings", []) if "key" in st}
    x = Extension(
        id=ext_id,
        name=_name(m),
        version=m["version"],
        trust=m.get("trust", "community"),
        status="installing",
        enabled=True,
        manifest=m,
        settings=defaults,
        grants=list(m.get("perms", [])),
        restarts=0,
    )
    s.add(x)
    await s.flush()
    await events.add(s, "ext.installing", actor=p.actor, params={"name": x.name, "version": x.version})
    _changed(s, x)
    after(s, lambda: _cmd("install", ext_id))
    return await _view(x)


def _name(m: dict[str, Any]) -> str:
    n = m.get("name")
    return (n.get("en") or next(iter(n.values()), m["id"])) if isinstance(n, dict) else str(n or m["id"])


def new_perms(x: Extension) -> list[str]:
    e = entry(x.id)
    if not e:
        return []
    return [g for g in e["manifest"].get("perms", []) if g not in (x.grants or [])]


async def update(s: AsyncSession, p: Principal, ext_id: str, grants: list[str] | None = None) -> ExtOut:
    p.need("admin")
    x = await get(s, ext_id)
    e = entry(ext_id)
    if not e or _ver(e["manifest"]["version"]) <= _ver(x.version):
        raise ApplicationError("ext_no_update", 409)
    if x.status in ("installing", "updating", "removing"):
        raise ApplicationError("ext_busy", 409)
    missing = new_perms(x)
    if missing and not set(missing) <= set(grants or []):
        raise ApplicationError("ext_grants", 422, perms=", ".join(missing))
    if missing:
        x.grants = [*x.grants, *missing]
        await kv().delete(f"ext:cred:{x.id}")
    x.status = "updating"
    await events.add(
        s,
        "ext.updating",
        actor=p.actor,
        params={"name": x.name, "version": e["manifest"]["version"], "from": x.version},
    )
    _changed(s, x)
    after(s, lambda: _cmd("update", ext_id))
    return await _view(x)


async def toggle(s: AsyncSession, p: Principal, ext_id: str) -> ExtOut:
    p.need("admin")
    x = await get(s, ext_id)
    if x.status in ("installing", "updating", "removing"):
        raise ApplicationError("ext_busy", 409)
    x.enabled = not x.enabled
    x.status = "starting" if x.enabled else "stopped"
    if x.enabled:
        x.restarts, x.error = 0, None
    await events.add(
        s,
        "ext.enabled" if x.enabled else "ext.disabled",
        "ok" if x.enabled else "warn",
        actor=p.actor,
        params={"name": x.name},
    )
    _changed(s, x)
    after(s, lambda: _cmd("start" if x.enabled else "stop", ext_id))
    return await _view(x)


async def restart(s: AsyncSession, p: Principal, ext_id: str) -> ExtOut:
    p.need("admin")
    x = await get(s, ext_id)
    if not x.enabled or x.status in ("installing", "updating", "removing"):
        raise ApplicationError("ext_busy", 409)
    x.status, x.restarts, x.error = "starting", 0, None
    await events.add(s, "ext.restart", actor=p.actor, params={"name": x.name})
    _changed(s, x)
    after(s, lambda: _cmd("restart", ext_id))
    return await _view(x)


async def remove(s: AsyncSession, p: Principal, ext_id: str) -> None:
    p.need("admin")
    x = await get(s, ext_id)
    x.status, x.enabled = "removing", False
    await events.add(s, "ext.removing", "warn", actor=p.actor, params={"name": x.name})
    _changed(s, x)
    after(s, lambda: _cmd("remove", ext_id))


async def configure(s: AsyncSession, p: Principal, ext_id: str, data: SettingsIn) -> ExtOut:
    p.need("admin")
    x = await get(s, ext_id)
    known = {st["key"]: st for st in x.manifest.get("settings", []) if "key" in st}
    bad = [k for k in data.values if k not in known]
    if bad:
        raise ApplicationError("validation", 422, detail=", ".join(bad))
    x.settings = {
        **x.settings,
        **{
            k: (secretbox.seal(str(v)) if known[k].get("type") == "secret" else v)
            for k, v in data.values.items()
            if not (known[k].get("type") == "secret" and v in ("", None))
        },
        **{k: "" for k, v in data.values.items() if known[k].get("type") == "secret" and v is None},
    }
    await events.add(s, "ext.configured", actor=p.actor, params={"name": x.name})
    _changed(s, x)
    if x.enabled:
        after(s, lambda: _cmd("restart", ext_id))
    return await _view(x)


async def purge(s: AsyncSession, ext_id: str) -> None:
    x = await s.get(Extension, ext_id)
    name = x.name if x else ext_id
    gone = [d for d in (await s.scalars(select(Device).where(Device.ext_id == ext_id))).all()]
    await s.execute(delete(Device).where(Device.ext_id == ext_id))
    if x:
        await s.delete(x)
    await events.add(s, "ext.removed", "warn", params={"name": name})

    async def push() -> None:
        for d in gone:
            try:
                for part in ("meta", "state", "avail"):
                    await mqtt.publish(f"hub/v1/ext/{ext_id}/dev/{d.address}/{part}", b"", qos=1, retain=True)
            except ApplicationError as e:
                _log.warning("ext_retained_clear_failed", ext=ext_id, device=d.id, error=str(e))
            await realtime.emit(
                "device_gone", {"id": d.id}, [f"room:{d.room_id or 'none'}", f"dev:{d.id}", "rooms:all"]
            )
        try:
            await mqtt.publish(f"hub/v1/ext/{ext_id}/status", b"", qos=1, retain=True)
        except ApplicationError as e:
            _log.warning("ext_retained_clear_failed", ext=ext_id, device=None, error=str(e))
        await realtime.emit("ext_gone", {"id": ext_id}, ["all"])
        await tasks.kick("flows.reindex")

    after(s, push)


async def status(
    s: AsyncSession,
    ext_id: str,
    state: str,
    pid: int | None = None,
    error: str | None = None,
    version: str | None = None,
) -> None:
    x = await s.get(Extension, ext_id)
    if x is None:
        return
    prev = x.status
    x.status, x.pid, x.error = state, pid if state == "running" else None, error
    if version:
        x.version = version
        e = entry(ext_id)
        if e and e["manifest"]["version"] == version:
            x.manifest = e["manifest"]
            defaults = {st["key"]: st.get("default") for st in x.manifest.get("settings", []) if "key" in st}
            cur = x.settings or {}
            x.settings = {k: cur.get(k, v) for k, v in defaults.items()}
    if state == "running":
        x.started_at = now()
        if prev in ("installing", "updating"):
            await events.add(
                s,
                "ext.installed" if prev == "installing" else "ext.updated",
                "ok",
                params={"name": x.name, "version": x.version},
            )
        await events.resolve(s, f"ext:{ext_id}")
    elif state == "error":
        x.restarts += 1
        await events.add(
            s, "ext.crashed", "crit", params={"name": x.name, "error": (error or "")[:300], "restarts": x.restarts}
        )
        await events.notify(
            s, f"ext:{ext_id}", "crit", "ext_error", {"name": x.name, "restarts": x.restarts}, f"ext/{ext_id}"
        )
    _changed(s, x)


async def logs(ext_id: str, limit: int = 200) -> list[str]:
    return list(reversed(await kv().lrange(f"ext:log:{ext_id}", 0, limit - 1)))


async def running(s: AsyncSession) -> list[Extension]:
    return list(
        (await s.scalars(select(Extension).where(Extension.enabled.is_(True), Extension.status == "running"))).all()
    )


async def blocks(s: AsyncSession) -> list[BlockDef]:
    res = []
    for x in await running(s):
        for b in x.manifest.get("blocks", []):
            kind = b.get("kind", "act")
            ins, outs = _IO.get(kind, (["ev"], ["ev"]))
            res.append(
                BlockDef(
                    key=f"{x.id}:{b['key']}",
                    kind=kind,
                    ins=b.get("ins", ins),
                    outs=b.get("outs", outs),
                    labels=b.get("labels", ["yes", "no"] if kind == "cond" else []),
                    params=b.get("params", []),
                    ext=x.id,
                    name=b.get("name"),
                    icon=b.get("icon"),
                )
            )
    return res


async def templates(s: AsyncSession) -> list[dict[str, Any]]:
    out_: list[dict[str, Any]] = []
    for x in (await s.scalars(select(Extension).where(Extension.enabled.is_(True)))).all():
        for tp in x.manifest.get("templates") or []:
            if isinstance(tp, dict) and tp.get("key") and isinstance(tp.get("graph"), dict):
                out_.append(
                    {
                        "key": f"{x.id}:{tp['key']}",
                        "name": tp.get("name") or tp["key"],
                        "description": tp.get("description"),
                        "ext": x.id,
                        "graph": tp["graph"],
                    }
                )
    return out_


async def contributions(s: AsyncSession) -> dict[str, Any]:
    pages, widgets = [], []
    for x in await running(s):
        m = x.manifest
        name = m.get("name") or x.name
        pages += [{**pg, "ext": x.id, "extName": name} for pg in m.get("pages", [])]
        widgets += [{**w, "ext": x.id, "extName": name} for w in m.get("widgets", [])]
    exts = [
        {
            "id": x.id,
            "name": x.manifest.get("name") or x.name,
            "icon": x.manifest.get("icon") or "ext",
            "status": x.status,
            "blocks": len(x.manifest.get("blocks", [])),
            "templates": len(x.manifest.get("templates", [])),
        }
        for x in (await s.scalars(select(Extension).order_by(Extension.id))).all()
    ]
    return {"pages": pages, "widgets": widgets, "exts": exts}


async def rpc(
    s: AsyncSession, ext_id: str, method: str, params: dict[str, Any], timeout: float = 10.0
) -> dict[str, Any]:
    x = await s.get(Extension, ext_id)
    if x is None or not x.enabled or x.status != "running":
        raise ApplicationError("ext_rpc_timeout", 503, ext=ext_id)
    corr = uuid.uuid4().hex
    try:
        res = await mqtt.request(
            f"hub/v1/ext/{ext_id}/rpc",
            {"method": method, "params": params},
            corr,
            timeout,
            mqtt.props(mqtt.RESP_TOPIC, corr, int(timeout)),
        )
    except ApplicationError as e:
        if e.code == "mqtt_timeout":
            raise ApplicationError("ext_rpc_timeout", 504, ext=x.name) from e
        raise
    if isinstance(res, dict) and res.get("error"):
        raise ApplicationError("ext_rpc_error", 502, ext=x.name, detail=str(res["error"])[:200])
    return res.get("result", res) if isinstance(res, dict) else {"result": res}


async def push(s: AsyncSession, text: str, level: str) -> int:
    sent = 0
    for x in await running(s):
        if "notifications.send" not in x.grants or not any(
            sv.startswith("notify") for sv in x.manifest.get("services", [])
        ):
            continue
        try:
            await rpc(s, x.id, "service", {"name": "notify", "text": text, "level": level})
            sent += 1
            await events.add(s, "ext.delivered", "ok", actor=f"ext:{x.id}", params={"name": x.name, "text": text[:120]})
        except ApplicationError as e:
            _log.warning("push_failed", ext=x.id, code=e.code)
    return sent


def ui_file(x: Extension, rel: str) -> pathlib.Path:
    src = source_for(x.id, x.version)
    base = src[0] if x.trust == "local" and src else EXT_DIR / x.id / x.version
    root = (base / "ui").resolve()
    f = (root / rel).resolve()
    if not f.is_file() or root not in f.parents:
        raise ApplicationError("ext_file_not_found", 404)
    return f


MEDIA_MAX = 52 * 1024 * 1024


async def core_call(s: AsyncSession, ext_id: str, method: str, params: dict[str, Any]) -> Any:
    from app.domain import devices
    from app.domain.common import Principal

    x = await s.get(Extension, ext_id)
    if x is None or x.status not in ("running", "starting", "installing", "updating"):
        raise ApplicationError("forbidden", 403)
    g = set(x.grants)
    p = Principal(id=f"ext:{ext_id}", username=f"ext:{ext_id}", name=x.name, role="admin")
    if method in ("devices.list", "devices.get"):
        if "devices.read" not in g:
            raise ApplicationError("ext_permission", 403, perm="devices.read")
        if method == "devices.get":
            return devices.view(await devices.get(s, params.get("id", "")))
        return await devices.listing(s, p, room=params.get("room", ""))
    if method == "devices.command":
        if "devices.control" not in g:
            raise ApplicationError("ext_permission", 403, perm="devices.control")
        return await devices.command(s, p, params.get("id", ""), params.get("values") or {}, actor=f"ext:{ext_id}")
    if method == "notify":
        if "notifications.send" not in g:
            raise ApplicationError("ext_permission", 403, perm="notifications.send")
        await events.notify(
            s,
            f"ext:{ext_id}:{params.get('key', 'msg')}",
            params.get("level", "info"),
            "flow_notify",
            {"text": str(params.get("text", ""))},
            f"ext/{ext_id}",
            touch=True,
        )
        return {"ok": True}
    if method == "event":
        await events.add(
            s,
            "ext.event",
            params.get("level", "info"),
            actor=f"ext:{ext_id}",
            params={"name": x.name, "text": str(params.get("text", ""))[:300]},
        )
        return {"ok": True}
    if method in ("rooms", "notifications"):
        if "devices.read" not in g:
            raise ApplicationError("ext_permission", 403, perm="devices.read")
        if method == "rooms":
            from app.domain import home as home_mod

            return [{"id": r.id, "name": r.name, "floor": r.floor} for r in await home_mod.rooms(s)]
        h = await events.home(s)
        lang = str((h.settings or {}).get("lang") or "uk")
        return [
            {"level": n.level, "type": n.type, "text": notice(n.type, lang, **(n.params or {}))}
            for n in await events.active(s)
        ]
    if method.startswith(("cameras.", "media.")):
        from app.domain import cameras, media

        if method == "cameras.mine":
            if cameras.PERM not in g:
                raise ApplicationError("ext_permission", 403, perm=cameras.PERM)
            return await cameras.for_driver(s, ext_id)
        if method == "cameras.event":
            return await cameras.report(s, ext_id, params, g)
        if method in ("cameras.health", "cameras.moved"):
            if cameras.PERM not in g:
                raise ApplicationError("ext_permission", 403, perm=cameras.PERM)
            fn = cameras.health if method == "cameras.health" else cameras.moved
            return await fn(s, ext_id, params)
        if method == "cameras.frame":
            if "cameras.stream" not in g:
                raise ApplicationError("ext_permission", 403, perm="cameras.stream")
            c, _, _ = await cameras.load(s, p, str(params.get("camera", "")))
            data = await cameras.still(c, sub=params.get("sub", True) is not False, fresh=bool(params.get("fresh")))
            return {"camera": c.id, "data": base64.b64encode(data).decode()}
        if method == "media.put":
            if "media.write" not in g:
                raise ApplicationError("ext_permission", 403, perm="media.write")
            return await cameras.put_photo(s, ext_id, params)
        if method == "cameras.list":
            if not g & {"cameras.stream", "cameras.events", "media.read"}:
                raise ApplicationError("ext_permission", 403, perm="cameras.stream")
            return [
                {
                    "id": c.id,
                    "name": c.name,
                    "deviceId": c.device_id,
                    "roomId": c.room_id,
                    "available": c.available,
                    "state": c.state,
                    "detect": c.record.get("detect") or {},
                    "zones": c.record.get("zones") or [],
                }
                for c in await cameras.listing(s, p)
            ]
        if method == "cameras.stream":
            if "cameras.stream" not in g:
                raise ApplicationError("ext_permission", 403, perm="cameras.stream")
            c = await cameras.one(s, p, str(params.get("camera", "")))
            sub = bool(params.get("sub")) and "sub" in c.streams
            return {"rtsp": rtc.rtsp(rtc.stream(c.id, sub)), "sub": sub}
        if method == "cameras.snapshot":
            if "media.write" not in g:
                raise ApplicationError("ext_permission", 403, perm="media.write")
            m = await cameras.capture(s, str(params.get("camera", "")), f"ext:{ext_id}", label="ext")
            return media.view(m)
        if method == "cameras.clip":
            if "media.write" not in g:
                raise ApplicationError("ext_permission", 403, perm="media.write")
            return await cameras.clip(
                s, None, str(params.get("camera", "")), int(params.get("seconds") or 15), f"ext:{ext_id}"
            )
        if method in ("media.list", "media.get"):
            if "media.read" not in g:
                raise ApplicationError("ext_permission", 403, perm="media.read")
            if method == "media.list":
                return await media.listing(
                    s,
                    p,
                    camera=str(params.get("camera", "")),
                    kind=str(params.get("kind", "")),
                    limit=int(params.get("limit") or 20),
                )
            m, f = await media.get(s, p, str(params.get("id", "")))
            if m.size > MEDIA_MAX:
                raise ApplicationError("validation", 422, detail="media larger than 52 MB")
            return {**msgspec.to_builtins(media.view(m)), "data": base64.b64encode(f.read_bytes()).decode()}
        raise ApplicationError("not_found", 404)
    if method == "home":
        h = await events.home(s)
        return {
            "lat": h.lat,
            "lon": h.lon,
            "timezone": h.timezone,
            "currency": h.currency,
            "name": h.name,
            "lang": (h.settings or {}).get("lang") or "uk",
        }
    raise ApplicationError("not_found", 404)
