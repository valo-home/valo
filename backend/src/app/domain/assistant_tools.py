"""Инструменты ИИ ассистента. Каждый вызывает функции ядра от имени пользователя, поэтому права проверяет ядро.

Виды инструментов: read только читает, write выполняется сразу и может быть отменен, confirm ждет кнопки Выполнить.
"""

import json
import os
import pathlib
import re
import time
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import devices, events, extensions, flows, home, manual, scenes, zigbee
from app.domain.common import ROLES, Principal
from app.lib.errors import ApplicationError
from app.lib.timeutil import zone

DOCS_DIR = pathlib.Path(os.environ.get("VALO_DOCS", "/app/docs"))
SRC_DIR = pathlib.Path(os.environ.get("VALO_SRC", "/app/src"))
EXT_DIR = pathlib.Path(os.environ.get("EXT_CATALOG", "/app/extensions/catalog.json")).parent / "packages"
TEXT_EXT = {".py", ".md", ".json", ".sql", ".toml", ".js", ".svelte", ".css", ".hcl", ".yml", ".yaml"}
MAX_RESULT = 12000

WIDGETS: dict[str, dict[str, Any]] = {
    "device": {"needs": ["device"], "about": "all readings of a device, its control, battery, update time"},
    "sensor": {"needs": ["device"], "about": "temperature and humidity large, 24 h min and max, chart"},
    "plug": {"needs": ["device"], "about": "power, voltage, current, energy today and total, power chart, switch"},
    "thermo": {"needs": ["device"], "about": "current temperature and setpoint buttons"},
    "value": {"needs": ["device", "cap"], "about": "one numeric capability in large digits with 24 h sparkline"},
    "chart": {"needs": ["device", "cap"], "about": "chart of a numeric capability, hours 24, 168 or 720"},
    "room": {"needs": ["room"], "about": "room temperature, humidity, lights and devices"},
    "lights": {"needs": ["room"], "about": "lights of a room with switches"},
    "scenes": {"needs": [], "about": "scene buttons"},
    "attention": {"needs": [], "about": "alarms, offline devices, open doors, low batteries"},
    "battery": {"needs": [], "about": "battery devices, lowest first"},
    "power": {"needs": [], "about": "plugs and meters by current power"},
    "leaks": {"needs": [], "about": "all leak sensors"},
    "doors": {"needs": [], "about": "all doors and windows"},
    "clock": {"needs": [], "about": "time, date, outside weather, calendar, next alarm"},
    "ext": {"needs": ["ext", "key"], "about": "widget of an installed extension, see widget_catalog"},
}

SUMMARY: dict[str, dict[str, str]] = {
    "create_room": {"uk": "Створено приміщення {name}", "ru": "Создано помещение {name}", "en": "Room {name} created"},
    "update_room": {"uk": "Змінено приміщення {room}", "ru": "Изменено помещение {room}", "en": "Room {room} updated"},
    "assign_devices": {
        "uk": "Пристрої ({n}) у приміщенні {room}",
        "ru": "Устройства ({n}) в помещении {room}",
        "en": "Devices ({n}) in room {room}",
    },
    "rename_device": {
        "uk": "Пристрій {old} перейменовано на {name}",
        "ru": "Устройство {old} переименовано в {name}",
        "en": "Device {old} renamed to {name}",
    },
    "create_dashboard": {
        "uk": "Створено панель {name}, віджетів {n}",
        "ru": "Создана панель {name}, виджетов {n}",
        "en": "Dashboard {name} created, {n} widgets",
    },
    "update_dashboard": {
        "uk": "Змінено панель {name}",
        "ru": "Изменена панель {name}",
        "en": "Dashboard {name} updated",
    },
    "add_widgets": {
        "uk": "На панель {name} додано віджетів {n}",
        "ru": "На панель {name} добавлено виджетов {n}",
        "en": "{n} widgets added to dashboard {name}",
    },
    "device_command": {
        "uk": "Команда {device}: {values}",
        "ru": "Команда {device}: {values}",
        "en": "Command {device}: {values}",
    },
    "apply_scene": {"uk": "Застосувати сцену {name}", "ru": "Применить сцену {name}", "en": "Apply scene {name}"},
    "delete_dashboard": {
        "uk": "Видалити панель {name}",
        "ru": "Удалить панель {name}",
        "en": "Delete dashboard {name}",
    },
    "delete_room": {"uk": "Видалити приміщення {name}", "ru": "Удалить помещение {name}", "en": "Delete room {name}"},
    "create_flow": {"uk": "Створити сценарій {name}", "ru": "Создать сценарий {name}", "en": "Create flow {name}"},
    "update_flow": {"uk": "Змінити сценарій {name}", "ru": "Изменить сценарий {name}", "en": "Update flow {name}"},
    "delete_flow": {"uk": "Видалити сценарій {name}", "ru": "Удалить сценарий {name}", "en": "Delete flow {name}"},
    "run_flow": {"uk": "Запустити сценарій {name}", "ru": "Запустить сценарий {name}", "en": "Run flow {name}"},
    "install_extension": {
        "uk": "Встановити розширення {name}",
        "ru": "Установить расширение {name}",
        "en": "Install extension {name}",
    },
    "zigbee_permit_join": {
        "uk": "Відкрити сопряження Zigbee на {seconds} с",
        "ru": "Открыть сопряжение Zigbee на {seconds} с",
        "en": "Open Zigbee pairing for {seconds} s",
    },
}


@dataclass
class Ctx:
    s: AsyncSession
    p: Principal
    lang: str
    undo: list[dict[str, Any]] = field(default_factory=list)
    summary: str = ""


Fn = Callable[[Ctx, dict[str, Any]], Awaitable[Any]]


@dataclass
class Tool:
    name: str
    about: str
    params: dict[str, Any]
    fn: Fn
    mode: str = "read"
    level: str = "guest"
    unrestricted: bool = False
    required: list[str] = field(default_factory=list)


def say(ctx: Ctx, key: str, **kw: Any) -> str:
    t = SUMMARY[key]
    return (t.get(ctx.lang) or t["en"]).format(**kw)


def clip(v: Any, n: int = 80) -> Any:
    return v[:n] if isinstance(v, str) else v


def short_state(state: dict[str, Any]) -> dict[str, Any]:
    return {k: clip(v) for k, v in state.items() if not k.startswith("_") and not isinstance(v, (dict, list))}


def compact(d: devices.DeviceOut, rooms: dict[str, str]) -> dict[str, Any]:
    return {
        "id": d.id,
        "name": d.name,
        "kind": d.kind,
        "room": rooms.get(d.room_id or "", None),
        "roomId": d.room_id,
        "source": "service " + (d.ext_id or "") if d.service else d.source,
        "available": d.available,
        "state": short_state(d.state),
    }


async def room_names(s: AsyncSession) -> dict[str, str]:
    return {r.id: r.name for r in await home.rooms(s)}


async def visible_device(ctx: Ctx, device_id: str) -> devices.DeviceOut:
    d = await devices.get(ctx.s, str(device_id))
    ctx.p.need_room(d.room_id)
    return devices.view(d)


async def t_overview(ctx: Ctx, a: dict[str, Any]) -> Any:
    h = await events.home(ctx.s)
    rooms = [r for r in await home.rooms(ctx.s) if ctx.p.room_ok(r.id)]
    every = await devices.listing(ctx.s, ctx.p)
    devs = [d for d in every if not d.service]
    services = [d for d in every if d.service]
    alarm_caps = ("leak", "smoke", "co", "gas")
    return {
        "home": h.name,
        "timezone": h.timezone,
        "now": datetime.now(zone(h.timezone)).strftime("%Y-%m-%d %H:%M %A"),
        "user": {"name": ctx.p.name, "role": ctx.p.role, "rooms": ctx.p.rooms or "all"},
        "rooms": [
            {"id": r.id, "name": r.name, "floor": r.floor, "devices": sum(d.room_id == r.id for d in devs)}
            for r in rooms
        ],
        "devices": len(devs),
        "bySource": dict(Counter(d.source for d in devs)),
        "services": [{"id": d.id, "name": d.name, "kind": d.kind, "extension": d.ext_id} for d in services],
        "unassigned": [d.name for d in devs if not d.room_id][:30],
        "offline": [d.name for d in every if not d.available][:30],
        "alarms": [d.name for d in every if any(d.state.get(k) is True for k in alarm_caps)],
        "lowBattery": [
            f"{d.name} {d.state['bat']}%"
            for d in every
            if isinstance(d.state.get("bat"), (int, float)) and d.state["bat"] < 15
        ],
        "dashboards": [{"id": b.id, "name": b.name, "widgets": len(b.widgets)} for b in await home.dashboards(ctx.s)],
        "flows": None if ctx.p.rooms else len(await flows.listing(ctx.s)),
        "extensions": [{"id": x.id, "name": x.name, "status": x.status} for x in await extensions.listing(ctx.s)],
    }


async def t_list_devices(ctx: Ctx, a: dict[str, Any]) -> Any:
    rooms = await room_names(ctx.s)
    devs = await devices.listing(ctx.s, ctx.p, room=str(a.get("room") or ""), q=str(a.get("query") or ""))
    kind = str(a.get("kind") or "")
    rows = [compact(d, rooms) for d in devs if not kind or d.kind == kind]
    limit = max(1, min(int(a.get("limit") or 80), 200))
    return {"total": len(rows), "devices": rows[:limit]}


async def t_get_device(ctx: Ctx, a: dict[str, Any]) -> Any:
    d = await visible_device(ctx, a["device_id"])
    rooms = await room_names(ctx.s)
    keep = ("model", "vendor", "description", "type", "lqi", "powerSource", "meta")
    return {
        "id": d.id,
        "name": d.name,
        "kind": d.kind,
        "source": d.source,
        "model": d.model,
        "vendor": d.vendor,
        "room": rooms.get(d.room_id or ""),
        "roomId": d.room_id,
        "available": d.available,
        "lastSeen": d.last_seen.isoformat() if d.last_seen else None,
        "caps": [
            {k: c[k] for k in ("id", "type", "unit", "access", "min", "max", "step", "values") if k in c}
            for c in d.caps
        ],
        "state": short_state(d.state),
        "attrs": {k: v for k, v in d.attrs.items() if k in keep},
    }


async def t_history(ctx: Ctx, a: dict[str, Any]) -> Any:
    d = await visible_device(ctx, a["device_id"])
    cap = str(a["cap"])
    if not any(c["id"] == cap for c in d.caps):
        raise ApplicationError("validation", 422, detail="cap")
    hours = max(1, min(int(a.get("hours") or 24), 720))
    h = await devices.history(ctx.s, d.id, cap, hours)
    pts = [p for p in h["points"] if isinstance(p[1], (int, float))]
    vals = [p[1] for p in pts]
    step = max(1, len(pts) // 48)
    return {
        "cap": cap,
        "hours": hours,
        "count": len(pts),
        "min": min(vals, default=None),
        "max": max(vals, default=None),
        "avg": round(sum(vals) / len(vals), 3) if vals else None,
        "last": vals[-1] if vals else None,
        "sample": [[datetime.fromtimestamp(p[0]).isoformat(timespec="minutes"), p[1]] for p in pts[::step]],
    }


async def t_rooms(ctx: Ctx, a: dict[str, Any]) -> Any:
    return [
        {"id": r.id, "name": r.name, "floor": r.floor, "outdoor": r.outdoor}
        for r in await home.rooms(ctx.s)
        if ctx.p.room_ok(r.id)
    ]


async def t_dashboards(ctx: Ctx, a: dict[str, Any]) -> Any:
    return [{"id": b.id, "name": b.name, "widgets": b.widgets} for b in await home.dashboards(ctx.s)]


async def t_widget_catalog(ctx: Ctx, a: dict[str, Any]) -> Any:
    contrib = await extensions.contributions(ctx.s)
    return {
        "types": WIDGETS,
        "fields": {
            "size": "optional, 'wide' for double width",
            "hours": "chart only: 24, 168 or 720",
            "cap": "capability id of the device, numeric for value and chart",
        },
        "extensionWidgets": [
            {"ext": w["ext"], "key": w["key"], "name": w.get("name")} for w in contrib.get("widgets", [])
        ],
    }


def restricted(ctx: Ctx) -> None:
    if ctx.p.rooms:
        raise ApplicationError("forbidden", 403)


async def t_flows(ctx: Ctx, a: dict[str, Any]) -> Any:
    restricted(ctx)
    return [
        {"id": f.id, "name": f.name, "enabled": f.enabled, "mode": f.mode, "lastResult": f.last_result, "dead": f.dead}
        for f in await flows.listing(ctx.s)
    ]


async def t_get_flow(ctx: Ctx, a: dict[str, Any]) -> Any:
    restricted(ctx)
    f = await flows.one(ctx.s, str(a["flow_id"]))
    return {"id": f.id, "name": f.name, "enabled": f.enabled, "mode": f.mode, "graph": f.graph}


async def t_blocks(ctx: Ctx, a: dict[str, Any]) -> Any:
    restricted(ctx)
    reg = await flows.registry(ctx.s)
    return {
        "graph": (
            "nodes: [{id, block, params, x, y}], edges: [{from, out, to, in}]. "
            "out is output port index, conditions use 0 yes 1 no"
        ),
        "blocks": [
            {"key": b.key, "kind": b.kind, "ins": b.ins, "outs": b.outs, "labels": b.labels, "params": b.params}
            for b in reg.values()
        ],
        "templates": [
            {"key": t["key"], "name": t.get("name"), "graph": t["graph"]}
            for t in [*flows.TEMPLATES, *await extensions.templates(ctx.s)]
        ],
    }


async def t_scenes(ctx: Ctx, a: dict[str, Any]) -> Any:
    return [{"id": x.id, "name": x.name, "devices": list(x.actions)} for x in await scenes.listing(ctx.s)]


async def t_extensions(ctx: Ctx, a: dict[str, Any]) -> Any:
    cat = await extensions.catalog(ctx.s)
    lang = ctx.lang

    def tx(v: Any) -> Any:
        return (v.get(lang) or v.get("en")) if isinstance(v, dict) else v

    return [
        {
            "id": c["id"],
            "name": tx(c["manifest"].get("name")),
            "description": tx(c["manifest"].get("description")),
            "installed": c.get("installed"),
            "version": c["manifest"].get("version"),
            "widgets": [w["key"] for w in c["manifest"].get("widgets", [])],
            "blocks": [b["key"] for b in c["manifest"].get("blocks", [])],
        }
        for c in cat
    ]


async def t_zigbee(ctx: Ctx, a: dict[str, Any]) -> Any:
    ctx.p.need("admin")
    info = await zigbee.info(ctx.s)
    weak = [r for r in await zigbee.health(ctx.s) if (r.get("lqi") or 255) < 60 or not r.get("available", True)]
    return {
        "info": {k: v for k, v in info.items() if not isinstance(v, (list, dict)) or k in ("coordinator", "network")},
        "weakOrOffline": weak[:30],
    }


async def t_events(ctx: Ctx, a: dict[str, Any]) -> Any:
    rows = await events.listing(
        ctx.s, ctx.p, device=str(a.get("device_id") or ""), limit=max(1, min(int(a.get("limit") or 30), 100))
    )
    return [
        {
            "ts": e.ts.isoformat(timespec="seconds"),
            "type": e.type,
            "level": e.level,
            "device": e.device_id,
            "params": e.params,
            "actor": e.actor,
        }
        for e in rows
    ]


def doc_files() -> list[pathlib.Path]:
    files = sorted(DOCS_DIR.glob("*.md")) if DOCS_DIR.is_dir() else []
    files += manual.files()
    files += sorted(EXT_DIR.glob("*/docs/*.md")) if EXT_DIR.is_dir() else []
    return files


def doc_name(f: pathlib.Path) -> str:
    if manual.HELP_DIR in f.parents:
        return f"help/{f.relative_to(manual.HELP_DIR)}"
    return str(f.relative_to(EXT_DIR.parent)) if EXT_DIR.parent in f.parents else f.name


async def t_search_docs(ctx: Ctx, a: dict[str, Any]) -> Any:
    terms = [t for t in re.findall(r"\w{3,}", str(a.get("query") or "").lower())]
    if not terms:
        raise ApplicationError("validation", 422, detail="query")
    hits = []
    for f in doc_files():
        for i, para in enumerate(f.read_text("utf-8", "replace").split("\n\n")):
            low = para.lower()
            score = sum(low.count(t) for t in terms)
            if score:
                hits.append((score, doc_name(f), i, para.strip()[:600]))
    hits.sort(key=lambda x: -x[0])
    return [{"doc": d, "part": i, "text": t} for _, d, i, t in hits[:8]]


async def t_read_doc(ctx: Ctx, a: dict[str, Any]) -> Any:
    want = str(a.get("doc") or "")
    for f in doc_files():
        if doc_name(f) == want:
            text = f.read_text("utf-8", "replace")
            start = max(0, int(a.get("offset") or 0))
            return {"doc": want, "size": len(text), "offset": start, "text": text[start : start + MAX_RESULT - 200]}
    return {"error": "not_found", "docs": [doc_name(f) for f in doc_files()][:80]}


def safe_src(path: str) -> pathlib.Path:
    rel = pathlib.PurePosixPath(path.strip().lstrip("/"))
    if ".." in rel.parts:
        raise ApplicationError("validation", 422, detail="path")
    target = (SRC_DIR / rel).resolve()
    if SRC_DIR.resolve() not in [target, *target.parents]:
        raise ApplicationError("validation", 422, detail="path")
    return target


async def t_list_source(ctx: Ctx, a: dict[str, Any]) -> Any:
    ctx.p.need("admin")
    base = safe_src(str(a.get("dir") or ""))
    if not base.is_dir():
        raise ApplicationError("not_found", 404)
    return sorted(
        f"{p.name}/" if p.is_dir() else p.name
        for p in base.iterdir()
        if not p.name.startswith((".", "__pycache__")) and (p.is_dir() or p.suffix in TEXT_EXT)
    )[:300]


async def t_read_source(ctx: Ctx, a: dict[str, Any]) -> Any:
    ctx.p.need("admin")
    f = safe_src(str(a["path"]))
    if not f.is_file() or f.suffix not in TEXT_EXT:
        raise ApplicationError("not_found", 404)
    lines = f.read_text("utf-8", "replace").splitlines()
    start = max(1, int(a.get("start_line") or 1))
    chunk, size = [], 0
    for n, line in enumerate(lines[start - 1 :], start):
        size += len(line) + 1
        if size > MAX_RESULT - 400:
            break
        chunk.append(f"{n}: {line}")
    return {"path": str(a["path"]), "lines": len(lines), "text": "\n".join(chunk)}


async def validate_widgets(ctx: Ctx, widgets: Any) -> list[dict[str, Any]]:
    if not isinstance(widgets, list) or len(widgets) > 60:
        raise ApplicationError("validation", 422, detail="widgets")
    contrib = {(w["ext"], w["key"]) for w in (await extensions.contributions(ctx.s)).get("widgets", [])}
    rooms = {r.id for r in await home.rooms(ctx.s)}
    out = []
    for i, w in enumerate(widgets):
        if not isinstance(w, dict) or w.get("type") not in WIDGETS:
            raise ApplicationError("validation", 422, detail=f"widgets[{i}].type")
        t = w["type"]
        item: dict[str, Any] = {"type": t, "id": f"w{int(time.time() * 1000):x}{i}"}
        for need in WIDGETS[t]["needs"]:
            if not w.get(need):
                raise ApplicationError("validation", 422, detail=f"widgets[{i}].{need}")
            item[need] = str(w[need])
        if "device" in item:
            d = await visible_device(ctx, item["device"])
            if "cap" in item and not any(c["id"] == item["cap"] and c["type"] == "num" for c in d.caps):
                raise ApplicationError("validation", 422, detail=f"widgets[{i}].cap")
        if "room" in item and item["room"] not in rooms:
            raise ApplicationError("room_not_found", 404)
        if t == "ext" and (item["ext"], item["key"]) not in contrib:
            raise ApplicationError("validation", 422, detail=f"widgets[{i}].ext")
        if t == "chart":
            item["hours"] = int(w.get("hours") or 24) if int(w.get("hours") or 24) in (24, 168, 720) else 24
        if w.get("size") == "wide":
            item["size"] = "wide"
        out.append(item)
    return out


async def t_create_room(ctx: Ctx, a: dict[str, Any]) -> Any:
    r = await home.create_room(
        ctx.s,
        ctx.p,
        home.RoomIn(name=str(a["name"])[:120], floor=int(a.get("floor") or 1), outdoor=bool(a.get("outdoor"))),
    )
    ctx.undo.append({"op": "delete_room", "room_id": r.id})
    ctx.summary = say(ctx, "create_room", name=r.name)
    return {"id": r.id, "name": r.name}


async def t_update_room(ctx: Ctx, a: dict[str, Any]) -> Any:
    old = next((r for r in await home.rooms(ctx.s) if r.id == a["room_id"]), None)
    if old is None:
        raise ApplicationError("room_not_found", 404)
    data = {k: a[k] for k in ("name", "floor", "outdoor") if k in a and a[k] is not None}
    r = await home.update_room(ctx.s, ctx.p, old.id, home.RoomPatch(**data))
    ctx.undo.append(
        {
            "op": "update_room",
            "room_id": old.id,
            "values": {"name": old.name, "floor": old.floor, "outdoor": old.outdoor},
        }
    )
    ctx.summary = say(ctx, "update_room", room=r.name)
    return {"id": r.id, "name": r.name, "floor": r.floor, "outdoor": r.outdoor}


async def t_assign(ctx: Ctx, a: dict[str, Any]) -> Any:
    room = a.get("room_id") or None
    rooms = await room_names(ctx.s)
    if room and room not in rooms:
        raise ApplicationError("room_not_found", 404)
    ids = [str(x) for x in (a.get("device_ids") or [])][:100]
    if not ids:
        raise ApplicationError("validation", 422, detail="device_ids")
    prev = {}
    for i in ids:
        d = await visible_device(ctx, i)
        prev[d.id] = d.room_id
        await devices.update(ctx.s, ctx.p, d.id, devices.DevicePatch(room_id=room))
    ctx.undo.append({"op": "set_rooms", "rooms": prev})
    ctx.summary = say(ctx, "assign_devices", n=len(ids), room=rooms.get(room or "", "-"))
    return {"moved": ids, "room": room}


async def t_rename(ctx: Ctx, a: dict[str, Any]) -> Any:
    d = await visible_device(ctx, a["device_id"])
    name = str(a["name"]).strip()[:120]
    if not name:
        raise ApplicationError("validation", 422, detail="name")
    await devices.update(ctx.s, ctx.p, d.id, devices.DevicePatch(name=name))
    ctx.undo.append({"op": "rename", "device_id": d.id, "name": d.name})
    ctx.summary = say(ctx, "rename_device", old=d.name, name=name)
    return {"id": d.id, "name": name}


async def dash(ctx: Ctx, dash_id: str) -> home.DashOut:
    b = next((x for x in await home.dashboards(ctx.s) if x.id == dash_id), None)
    if b is None:
        raise ApplicationError("dashboard_not_found", 404)
    return b


async def t_create_dash(ctx: Ctx, a: dict[str, Any]) -> Any:
    widgets = await validate_widgets(ctx, a.get("widgets") or [])
    b = await home.create_dashboard(ctx.s, ctx.p, home.DashIn(name=str(a["name"])[:120], widgets=widgets))
    ctx.undo.append({"op": "delete_dashboard", "dashboard_id": b.id})
    ctx.summary = say(ctx, "create_dashboard", name=b.name, n=len(widgets))
    return {"id": b.id, "name": b.name, "widgets": len(widgets), "link": f"/boards/{b.id}"}


async def t_update_dash(ctx: Ctx, a: dict[str, Any]) -> Any:
    old = await dash(ctx, str(a["dashboard_id"]))
    data: dict[str, Any] = {}
    if a.get("name"):
        data["name"] = str(a["name"])[:120]
    if "widgets" in a and a["widgets"] is not None:
        data["widgets"] = await validate_widgets(ctx, a["widgets"])
    b = await home.update_dashboard(ctx.s, ctx.p, old.id, home.DashPatch(**data))
    ctx.undo.append({"op": "set_dashboard", "dashboard_id": old.id, "name": old.name, "widgets": old.widgets})
    ctx.summary = say(ctx, "update_dashboard", name=b.name)
    return {"id": b.id, "name": b.name, "widgets": len(b.widgets)}


async def t_add_widgets(ctx: Ctx, a: dict[str, Any]) -> Any:
    old = await dash(ctx, str(a["dashboard_id"]))
    new = await validate_widgets(ctx, a.get("widgets") or [])
    b = await home.update_dashboard(ctx.s, ctx.p, old.id, home.DashPatch(widgets=[*old.widgets, *new]))
    ctx.undo.append({"op": "set_dashboard", "dashboard_id": old.id, "name": old.name, "widgets": old.widgets})
    ctx.summary = say(ctx, "add_widgets", name=b.name, n=len(new))
    return {"id": b.id, "widgets": len(b.widgets)}


def fmt_values(values: dict[str, Any]) -> str:
    return ", ".join(f"{k}={json.dumps(v, ensure_ascii=False)}" for k, v in values.items())[:200]


async def t_command(ctx: Ctx, a: dict[str, Any]) -> Any:
    d = await visible_device(ctx, a["device_id"])
    values = a.get("values")
    if not isinstance(values, dict) or not values:
        raise ApplicationError("validation", 422, detail="values")
    ctx.summary = say(ctx, "device_command", device=d.name, values=fmt_values(values))
    return lambda: devices.command(ctx.s, ctx.p, d.id, values)


async def t_scene(ctx: Ctx, a: dict[str, Any]) -> Any:
    sc = await scenes.get(ctx.s, str(a["scene_id"]))
    ctx.summary = say(ctx, "apply_scene", name=sc.name)
    return lambda: scenes.apply(ctx.s, ctx.p, sc.id)


async def t_delete_dash(ctx: Ctx, a: dict[str, Any]) -> Any:
    b = await dash(ctx, str(a["dashboard_id"]))
    ctx.summary = say(ctx, "delete_dashboard", name=b.name)
    return lambda: home.delete_dashboard(ctx.s, ctx.p, b.id)


async def t_delete_room(ctx: Ctx, a: dict[str, Any]) -> Any:
    r = next((x for x in await home.rooms(ctx.s) if x.id == a["room_id"]), None)
    if r is None:
        raise ApplicationError("room_not_found", 404)
    ctx.summary = say(ctx, "delete_room", name=r.name)
    return lambda: home.delete_room(ctx.s, ctx.p, r.id)


async def t_create_flow(ctx: Ctx, a: dict[str, Any]) -> Any:
    restricted(ctx)
    graph = a.get("graph")
    if not isinstance(graph, dict) or not isinstance(graph.get("nodes"), list):
        raise ApplicationError("validation", 422, detail="graph")
    reg = await flows.registry(ctx.s)
    if dead := flows.dead_blocks(graph, reg):
        raise ApplicationError("flow_dead", 409, block=dead[0])
    data = flows.FlowIn(
        name=str(a["name"])[:120],
        graph=graph,
        enabled=bool(a.get("enabled", True)),
        mode=str(a.get("mode") or "single"),
    )
    ctx.summary = say(ctx, "create_flow", name=data.name)
    return lambda: flows.create(ctx.s, ctx.p, data)


async def t_update_flow(ctx: Ctx, a: dict[str, Any]) -> Any:
    restricted(ctx)
    f = await flows.one(ctx.s, str(a["flow_id"]))
    data: dict[str, Any] = {k: a[k] for k in ("name", "enabled", "mode") if a.get(k) is not None}
    if a.get("graph") is not None:
        if not isinstance(a["graph"], dict) or not isinstance(a["graph"].get("nodes"), list):
            raise ApplicationError("validation", 422, detail="graph")
        if dead := flows.dead_blocks(a["graph"], await flows.registry(ctx.s)):
            raise ApplicationError("flow_dead", 409, block=dead[0])
        data["graph"] = a["graph"]
    ctx.summary = say(ctx, "update_flow", name=f.name)
    return lambda: flows.update(ctx.s, ctx.p, f.id, flows.FlowPatch(**data))


async def t_delete_flow(ctx: Ctx, a: dict[str, Any]) -> Any:
    restricted(ctx)
    f = await flows.one(ctx.s, str(a["flow_id"]))
    ctx.summary = say(ctx, "delete_flow", name=f.name)
    return lambda: flows.remove(ctx.s, ctx.p, f.id)


async def t_run_flow(ctx: Ctx, a: dict[str, Any]) -> Any:
    restricted(ctx)
    f = await flows.one(ctx.s, str(a["flow_id"]))
    ctx.summary = say(ctx, "run_flow", name=f.name)
    return lambda: flows.manual(ctx.s, ctx.p, f.id)


async def t_install(ctx: Ctx, a: dict[str, Any]) -> Any:
    ctx.p.need("admin")
    e = extensions.entry(str(a["ext_id"]))
    if e is None:
        raise ApplicationError("ext_not_found", 404)
    m = e["manifest"]
    name = m.get("name")
    ctx.summary = say(
        ctx, "install_extension", name=(name.get(ctx.lang) or name.get("en")) if isinstance(name, dict) else name
    )
    return lambda: extensions.install(ctx.s, ctx.p, m["id"], extensions.InstallIn(grants=list(m.get("perms", []))))


async def t_permit(ctx: Ctx, a: dict[str, Any]) -> Any:
    ctx.p.need("admin")
    seconds = max(30, min(int(a.get("seconds") or 254), 254))
    ctx.summary = say(ctx, "zigbee_permit_join", seconds=seconds)
    return lambda: zigbee.permit_join(ctx.s, ctx.p, seconds, None)


def P(t: str, about: str, **kw: Any) -> dict[str, Any]:
    return {"type": t, "description": about, **kw}


WIDGET_SCHEMA = P(
    "array",
    "widgets, see widget_catalog. Example {type: 'chart', device: '<id>', cap: 'v', hours: 24, size: 'wide'}",
    items={"type": "object", "additionalProperties": True},
)

TOOLS: list[Tool] = [
    Tool(
        "home_overview",
        "Summary of the home: rooms, physical device count by source, extension services (weather, calendar and "
        "similar, not devices), offline, alarms, low batteries, dashboards, extensions, local time",
        {},
        t_overview,
    ),
    Tool(
        "list_devices",
        "Find devices by room id, kind or name. Returns id, name, kind, room and compact state",
        {
            "room": P("string", "room id"),
            "kind": P("string", "device kind such as plug, clim, light, leak"),
            "query": P("string", "part of name, model or id"),
            "limit": P("integer", "max rows, default 80"),
        },
        t_list_devices,
    ),
    Tool(
        "get_device",
        "Full device: capabilities with types, units and access, state, model, room, last seen",
        {"device_id": P("string", "device id")},
        t_get_device,
        required=["device_id"],
    ),
    Tool(
        "device_history",
        "History of one capability: min, max, average, last and a sample of points",
        {
            "device_id": P("string", "device id"),
            "cap": P("string", "capability id, for example t, h, w, v, a, kwh"),
            "hours": P("integer", "1 to 720, default 24"),
        },
        t_history,
        required=["device_id", "cap"],
    ),
    Tool("list_rooms", "Rooms with ids, names and floors", {}, t_rooms),
    Tool("list_dashboards", "Dashboards with their widgets", {}, t_dashboards),
    Tool("widget_catalog", "Widget types, required fields and widgets of installed extensions", {}, t_widget_catalog),
    Tool("list_flows", "Automation flows with state and last result", {}, t_flows, unrestricted=True),
    Tool(
        "get_flow",
        "One flow with its graph",
        {"flow_id": P("string", "flow id")},
        t_get_flow,
        unrestricted=True,
        required=["flow_id"],
    ),
    Tool(
        "flow_blocks",
        "Flow block catalog with parameters, graph format and ready templates",
        {},
        t_blocks,
        unrestricted=True,
    ),
    Tool("list_scenes", "Scenes", {}, t_scenes),
    Tool("list_extensions", "Extensions catalog with installed versions, widgets and flow blocks", {}, t_extensions),
    Tool(
        "zigbee_info", "Zigbee coordinator, channel, network and weak or offline devices", {}, t_zigbee, level="admin"
    ),
    Tool(
        "recent_events",
        "Recent journal events, optionally of one device",
        {"device_id": P("string", "device id"), "limit": P("integer", "max 100")},
        t_events,
    ),
    Tool(
        "search_docs",
        "Search Valo documentation and extension guides: architecture, operations, Zigbee, MQTT format, extensions",
        {"query": P("string", "search words")},
        t_search_docs,
        required=["query"],
    ),
    Tool(
        "read_doc",
        "Read a documentation file found by search_docs",
        {"doc": P("string", "doc name from search_docs"), "offset": P("integer", "character offset")},
        t_read_doc,
        required=["doc"],
    ),
    Tool(
        "list_source",
        "List Valo backend source directory (read only), for example app/domain",
        {"dir": P("string", "directory relative to source root")},
        t_list_source,
        level="admin",
    ),
    Tool(
        "read_source",
        "Read a Valo backend source file (read only) with line numbers",
        {
            "path": P("string", "file relative to source root, for example app/domain/adapters.py"),
            "start_line": P("integer", "first line"),
        },
        t_read_source,
        level="admin",
        required=["path"],
    ),
    Tool(
        "create_room",
        "Create a room",
        {"name": P("string", "room name"), "floor": P("integer", "floor"), "outdoor": P("boolean", "outdoor area")},
        t_create_room,
        "write",
        "admin",
        required=["name"],
    ),
    Tool(
        "update_room",
        "Rename a room or change floor or outdoor flag",
        {
            "room_id": P("string", "room id"),
            "name": P("string", "new name"),
            "floor": P("integer", "floor"),
            "outdoor": P("boolean", "outdoor"),
        },
        t_update_room,
        "write",
        "admin",
        required=["room_id"],
    ),
    Tool(
        "assign_devices",
        "Put devices into a room, room_id null removes them from rooms",
        {
            "device_ids": P("array", "device ids", items={"type": "string"}),
            "room_id": P(["string", "null"], "room id or null"),
        },
        t_assign,
        "write",
        "admin",
        required=["device_ids", "room_id"],
    ),
    Tool(
        "rename_device",
        "Rename a device",
        {"device_id": P("string", "device id"), "name": P("string", "new name")},
        t_rename,
        "write",
        "admin",
        required=["device_id", "name"],
    ),
    Tool(
        "create_dashboard",
        "Create a dashboard with widgets",
        {"name": P("string", "dashboard name"), "widgets": WIDGET_SCHEMA},
        t_create_dash,
        "write",
        "member",
        required=["name", "widgets"],
    ),
    Tool(
        "update_dashboard",
        "Rename a dashboard or replace all its widgets",
        {"dashboard_id": P("string", "dashboard id"), "name": P("string", "new name"), "widgets": WIDGET_SCHEMA},
        t_update_dash,
        "write",
        "member",
        required=["dashboard_id"],
    ),
    Tool(
        "add_widgets",
        "Append widgets to a dashboard",
        {"dashboard_id": P("string", "dashboard id"), "widgets": WIDGET_SCHEMA},
        t_add_widgets,
        "write",
        "member",
        required=["dashboard_id", "widgets"],
    ),
    Tool(
        "device_command",
        "Send a command to a device, values use capability ids like {on: true} or {sp: 21.5}. Needs user confirmation",
        {"device_id": P("string", "device id"), "values": P("object", "capability values", additionalProperties=True)},
        t_command,
        "confirm",
        "member",
        required=["device_id", "values"],
    ),
    Tool(
        "apply_scene",
        "Apply a scene. Needs user confirmation",
        {"scene_id": P("string", "scene id")},
        t_scene,
        "confirm",
        "member",
        required=["scene_id"],
    ),
    Tool(
        "delete_dashboard",
        "Delete a dashboard. Needs user confirmation",
        {"dashboard_id": P("string", "dashboard id")},
        t_delete_dash,
        "confirm",
        "member",
        required=["dashboard_id"],
    ),
    Tool(
        "delete_room",
        "Delete a room, its devices stay without room. Needs user confirmation",
        {"room_id": P("string", "room id")},
        t_delete_room,
        "confirm",
        "admin",
        required=["room_id"],
    ),
    Tool(
        "create_flow",
        "Create an automation flow from a graph, see flow_blocks. Needs user confirmation",
        {
            "name": P("string", "flow name"),
            "graph": P("object", "flow graph", additionalProperties=True),
            "enabled": P("boolean", "enable now"),
            "mode": P("string", "single, restart, queued or parallel"),
        },
        t_create_flow,
        "confirm",
        "admin",
        True,
        ["name", "graph"],
    ),
    Tool(
        "update_flow",
        "Change a flow name, graph, mode or enabled state. Needs user confirmation",
        {
            "flow_id": P("string", "flow id"),
            "name": P("string", "name"),
            "graph": P("object", "new graph", additionalProperties=True),
            "enabled": P("boolean", "enabled"),
            "mode": P("string", "mode"),
        },
        t_update_flow,
        "confirm",
        "admin",
        True,
        ["flow_id"],
    ),
    Tool(
        "delete_flow",
        "Delete a flow. Needs user confirmation",
        {"flow_id": P("string", "flow id")},
        t_delete_flow,
        "confirm",
        "admin",
        True,
        ["flow_id"],
    ),
    Tool(
        "run_flow",
        "Run a flow manually. Needs user confirmation",
        {"flow_id": P("string", "flow id")},
        t_run_flow,
        "confirm",
        "member",
        True,
        ["flow_id"],
    ),
    Tool(
        "install_extension",
        "Install an extension from the catalog with its permissions. Needs user confirmation",
        {"ext_id": P("string", "extension id")},
        t_install,
        "confirm",
        "admin",
        required=["ext_id"],
    ),
    Tool(
        "zigbee_permit_join",
        "Open Zigbee pairing so a new device can join. Needs user confirmation",
        {"seconds": P("integer", "30 to 254")},
        t_permit,
        "confirm",
        "admin",
    ),
]
BY_NAME = {t.name: t for t in TOOLS}


def allowed(t: Tool, p: Principal) -> bool:
    return p.level() >= ROLES[t.level] and not (t.unrestricted and p.rooms)


def specs(p: Principal) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.about,
                "parameters": {"type": "object", "properties": t.params, "required": t.required},
            },
        }
        for t in TOOLS
        if allowed(t, p)
    ]


async def undo(s: AsyncSession, p: Principal, ops: list[dict[str, Any]]) -> None:
    for op in reversed(ops):
        kind = op.get("op")
        if kind == "delete_room":
            await home.delete_room(s, p, op["room_id"])
        elif kind == "update_room":
            await home.update_room(s, p, op["room_id"], home.RoomPatch(**op["values"]))
        elif kind == "set_rooms":
            for did, room in op["rooms"].items():
                await devices.update(s, p, did, devices.DevicePatch(room_id=room))
        elif kind == "rename":
            await devices.update(s, p, op["device_id"], devices.DevicePatch(name=op["name"]))
        elif kind == "delete_dashboard":
            await home.delete_dashboard(s, p, op["dashboard_id"])
        elif kind == "set_dashboard":
            await home.update_dashboard(
                s, p, op["dashboard_id"], home.DashPatch(name=op["name"], widgets=op["widgets"])
            )
        else:
            raise ApplicationError("validation", 422, detail="undo")


BUTTONS = {
    "de": ("Ausführen", "Rückgängig"),
    "en": ("Execute", "Undo"),
    "es": ("Ejecutar", "Deshacer"),
    "fr": ("Exécuter", "Annuler"),
    "ja": ("実行", "元に戻す"),
    "ru": ("Выполнить", "Отменить"),
    "uk": ("Виконати", "Скасувати"),
}

RULES = [
    "Use tools to look things up. Never invent device, room, dashboard or flow ids, find them first "
    "(home_overview, list_devices, get_device)",
    "Capability ids follow Valo conventions: on, bri, ct, color, t (temperature °C), h (humidity %), w (power W), "
    "v (voltage V), a (current A), kwh (energy), bat (%), leak, smoke, co, gas, occ (motion), open (contact), "
    "pos (blind %), sp or target (setpoint), lqi. Channels of multi gang devices use suffixes like on_l1",
    "Device data comes from Zigbee2MQTT exposes or MQTT topics. For questions about formats, setup or architecture "
    "use search_docs and read_doc, admins can also read backend source with list_source and read_source",
    "Dashboards: build widgets from widget_catalog. A chart of a plug voltage is "
    '{type: "chart", device: "<id>", cap: "v", hours: 24}. Check the device has the capability before adding it',
    "Room, device name and dashboard changes run at once and the user can undo them. Device commands, scenes, flows, "
    "deletions, extension install and Zigbee pairing need the user to press the confirm button on a card: "
    "call the tool once, then say what will happen and that the user has to confirm. Do not repeat the call",
    "If a tool returns an error, explain it plainly and suggest what to do. If the request is ambiguous, "
    "ask a short question",
    "Devices with source service are services of installed extensions (weather, calendar, timers, energy totals). "
    "When the user asks how many devices there are, count devices only and name services separately",
    "Keep answers short and concrete. Markdown with headings, lists, bold and inline code is rendered, tables are not",
]


def system_prompt(home_name: str, lang: str, p: Principal, local_now: str) -> str:
    level = {0: "guest, read only", 1: "member", 2: "admin", 3: "owner"}.get(p.level(), "guest")
    limit = f", limited to rooms {', '.join(p.rooms)}" if p.rooms else ""
    ok, undo = BUTTONS.get(lang, BUTTONS["en"])
    head = [
        "You are the assistant of Valo, a self hosted smart home hub (Zigbee2MQTT, MQTT, PostgreSQL).",
        f"Home: {home_name}. Local time: {local_now}.",
        f"User: {p.name}, role {level}{limit}. Always answer in the user's language (interface language {lang}).",
        "",
        f'Card buttons in the interface: confirm "{ok}", undo "{undo}". Use these names.',
        "",
        "How to work",
    ]
    return "\n".join([*head, *(f"- {r}" for r in RULES)]) + "\n"
