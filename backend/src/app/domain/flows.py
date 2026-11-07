import json
import uuid
from collections import deque
from datetime import datetime, timedelta
from fnmatch import fnmatch
from typing import Any

from paho.mqtt.client import topic_matches_sub
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import after, now
from app.db.models import Flow, FlowRun, FlowVersion
from app.domain import events, extensions
from app.domain.blocks import BLOCKS, EXEC, BlockDef, Run, compare, render
from app.domain.common import UNSET, Principal, S, Unset, after_cursor, cursor, out, patch, slug
from app.lib import log, realtime, tasks
from app.lib.errors import ApplicationError, message
from app.lib.kv import kv
from app.lib.timeutil import cron_match, hm, sun, zone

_log = log.get("flows")
MODES = ("single", "restart", "queued", "parallel")


class FlowOut(S):
    id: str
    name: str
    enabled: bool
    mode: str
    graph: dict[str, Any]
    version: int
    last_run_at: datetime | None
    last_result: str | None
    runs: int
    updated_at: datetime
    dead: list[str] = []


class FlowIn(S):
    name: str
    mode: str = "single"
    enabled: bool = True
    graph: dict[str, Any] = {}
    id: str | None = None


class FlowPatch(S):
    name: str | Unset = UNSET
    mode: str | Unset = UNSET
    enabled: bool | Unset = UNSET
    graph: dict[str, Any] | Unset = UNSET


class TestIn(S):
    graph: dict[str, Any] | None = None
    node: str | None = None


class RunOut(S):
    id: uuid.UUID
    flow_id: str
    status: str
    dry: bool
    trace: list[Any]
    started_at: datetime
    finished_at: datetime | None
    cause_id: int | None


class VersionOut(S):
    version: int
    author: str
    created_at: datetime
    graph: dict[str, Any]


TEMPLATES = [
    {
        "key": "light_motion",
        "graph": {
            "nodes": [
                {"id": "t", "block": "state", "params": {"cap": "occ", "to": True}, "x": 24, "y": 60},
                {"id": "c", "block": "compare", "params": {"cap": "lux", "op": "lt", "value": 40}, "x": 230, "y": 60},
                {"id": "a", "block": "command", "params": {"values": {"on": True}}, "x": 436, "y": 40},
                {"id": "w", "block": "wait", "params": {"cap": "occ", "to": False, "timeout": 600}, "x": 642, "y": 40},
                {"id": "o", "block": "command", "params": {"values": {"on": False}}, "x": 848, "y": 40},
            ],
            "edges": [
                {"from": "t", "out": 0, "to": "c", "in": 0},
                {"from": "c", "out": 0, "to": "a", "in": 0},
                {"from": "a", "out": 0, "to": "w", "in": 0},
                {"from": "w", "out": 0, "to": "o", "in": 0},
                {"from": "w", "out": 1, "to": "o", "in": 0},
            ],
        },
    },
    {
        "key": "leak_alert",
        "graph": {
            "nodes": [
                {"id": "t", "block": "state", "params": {"cap": "leak", "to": True}, "x": 24, "y": 120},
                {
                    "id": "n",
                    "block": "notify",
                    "params": {"text": "", "level": "crit", "push": True},
                    "x": 230,
                    "y": 60,
                },
                {"id": "v", "block": "command", "params": {"values": {"on": False}}, "x": 230, "y": 200},
            ],
            "edges": [{"from": "t", "out": 0, "to": "n", "in": 0}, {"from": "t", "out": 0, "to": "v", "in": 0}],
        },
    },
    {
        "key": "window_heating",
        "graph": {
            "nodes": [
                {"id": "t", "block": "state", "params": {"cap": "open", "to": True}, "x": 24, "y": 60},
                {"id": "d", "block": "delay", "params": {"seconds": 120}, "x": 230, "y": 60},
                {
                    "id": "c",
                    "block": "compare",
                    "params": {"cap": "open", "op": "eq", "value": True},
                    "x": 436,
                    "y": 60,
                },
                {"id": "a", "block": "command", "params": {"values": {"sp": 7}}, "x": 642, "y": 40},
            ],
            "edges": [
                {"from": "t", "out": 0, "to": "d", "in": 0},
                {"from": "d", "out": 0, "to": "c", "in": 0},
                {"from": "c", "out": 0, "to": "a", "in": 0},
            ],
        },
    },
    {
        "key": "sunset_lights",
        "graph": {
            "nodes": [
                {
                    "id": "t",
                    "block": "sun",
                    "params": {"event": "sunset", "offset": -15, "fallback": "16:00"},
                    "x": 24,
                    "y": 60,
                },
                {"id": "s", "block": "scene", "params": {}, "x": 230, "y": 60},
            ],
            "edges": [{"from": "t", "out": 0, "to": "s", "in": 0}],
        },
    },
    {
        "key": "plug_cycle",
        "graph": {
            "nodes": [
                {"id": "t", "block": "schedule", "params": {"cron": "*/15 * * * *"}, "x": 24, "y": 60},
                {"id": "a", "block": "command", "params": {"values": {"on": True}}, "x": 230, "y": 60},
                {"id": "d", "block": "delay", "params": {"seconds": 300}, "x": 436, "y": 60},
                {"id": "o", "block": "command", "params": {"values": {"on": False}}, "x": 642, "y": 60},
            ],
            "edges": [
                {"from": "t", "out": 0, "to": "a", "in": 0},
                {"from": "a", "out": 0, "to": "d", "in": 0},
                {"from": "d", "out": 0, "to": "o", "in": 0},
            ],
        },
    },
    {
        "key": "camera_night_motion",
        "graph": {
            "nodes": [
                {"id": "t", "block": "camera_event", "params": {"label": "motion", "phase": "start"}, "x": 24, "y": 60},
                {"id": "w", "block": "time_window", "params": {"from": "23:00", "to": "07:00"}, "x": 230, "y": 60},
                {"id": "s", "block": "snapshot", "params": {}, "x": 436, "y": 40},
                {
                    "id": "n",
                    "block": "notify",
                    "params": {"text": "{label}: {device}, {time}. {snapshot}", "level": "warn", "push": True},
                    "x": 642,
                    "y": 40,
                },
            ],
            "edges": [
                {"from": "t", "out": 0, "to": "w", "in": 0},
                {"from": "w", "out": 0, "to": "s", "in": 0},
                {"from": "s", "out": 0, "to": "n", "in": 0},
            ],
        },
    },
    {
        "key": "smoke_clip",
        "graph": {
            "nodes": [
                {"id": "t", "block": "state", "params": {"cap": "smoke", "to": True}, "x": 24, "y": 120},
                {"id": "c", "block": "clip", "params": {"seconds": 60}, "x": 230, "y": 60},
                {"id": "c2", "block": "clip", "params": {"seconds": 60}, "x": 230, "y": 200},
                {
                    "id": "n",
                    "block": "notify",
                    "params": {"text": "{device}, {room}, {time}", "level": "crit", "push": True},
                    "x": 436,
                    "y": 120,
                },
            ],
            "edges": [
                {"from": "t", "out": 0, "to": "c", "in": 0},
                {"from": "t", "out": 0, "to": "c2", "in": 0},
                {"from": "t", "out": 0, "to": "n", "in": 0},
            ],
        },
    },
    {
        "key": "cameras_away",
        "graph": {
            "nodes": [
                {"id": "t", "block": "manual", "params": {}, "x": 24, "y": 60},
                {
                    "id": "p",
                    "block": "camera_set",
                    "params": {"setting": "privacy", "value": "off"},
                    "x": 230,
                    "y": 60,
                },
                {"id": "m", "block": "camera_set", "params": {"setting": "motion", "value": "on"}, "x": 436, "y": 60},
                {
                    "id": "r",
                    "block": "camera_set",
                    "params": {"setting": "record", "value": "continuous"},
                    "x": 642,
                    "y": 60,
                },
            ],
            "edges": [
                {"from": "t", "out": 0, "to": "p", "in": 0},
                {"from": "p", "out": 0, "to": "m", "in": 0},
                {"from": "m", "out": 0, "to": "r", "in": 0},
            ],
        },
    },
    {
        "key": "cameras_home",
        "graph": {
            "nodes": [
                {"id": "t", "block": "manual", "params": {}, "x": 24, "y": 60},
                {
                    "id": "r",
                    "block": "camera_set",
                    "params": {"setting": "record", "value": "events"},
                    "x": 230,
                    "y": 60,
                },
                {"id": "p", "block": "camera_set", "params": {"setting": "privacy", "value": "on"}, "x": 436, "y": 60},
            ],
            "edges": [{"from": "t", "out": 0, "to": "r", "in": 0}, {"from": "r", "out": 0, "to": "p", "in": 0}],
        },
    },
    {
        "key": "offline_notify",
        "graph": {
            "nodes": [
                {
                    "id": "t",
                    "block": "log_event",
                    "params": {"pattern": "device.offline", "level": "warn"},
                    "x": 24,
                    "y": 60,
                },
                {
                    "id": "n",
                    "block": "notify",
                    "params": {"text": "", "level": "warn", "push": True},
                    "x": 230,
                    "y": 60,
                },
            ],
            "edges": [{"from": "t", "out": 0, "to": "n", "in": 0}],
        },
    },
]


async def registry(s: AsyncSession) -> dict[str, BlockDef]:
    return {**BLOCKS, **{b.key: b for b in await extensions.blocks(s)}}


def dead_blocks(graph: dict[str, Any], reg: dict[str, BlockDef]) -> list[str]:
    return sorted({n.get("block", "") for n in graph.get("nodes", []) if n.get("block") not in reg})


def validate(graph: dict[str, Any], reg: dict[str, BlockDef]) -> dict[str, Any]:
    if not isinstance(graph, dict):
        raise ApplicationError("flow_invalid", 422, detail="graph")
    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []
    ids = [n.get("id") for n in nodes]
    if len(ids) != len(set(ids)) or not all(isinstance(i, str) and i for i in ids):
        raise ApplicationError("flow_invalid", 422, detail="node ids")
    by = {n["id"]: n for n in nodes}
    for e in edges:
        a, b = by.get(e.get("from")), by.get(e.get("to"))
        if a is None or b is None:
            raise ApplicationError("flow_invalid", 422, detail="edge")
        ba, bb = reg.get(a.get("block")), reg.get(b.get("block"))
        if ba is None or bb is None:
            continue
        o, i = int(e.get("out", 0)), int(e.get("in", 0))
        if o >= len(ba.outs) or i >= len(bb.ins):
            raise ApplicationError("flow_invalid", 422, detail="port")
        src, dst = ba.outs[o], bb.ins[i]
        if "any" not in (src, dst) and src != dst:
            raise ApplicationError("flow_ports", 422, src=src, dst=dst)
    return {"nodes": nodes, "edges": edges}


def view(f: Flow, reg: dict[str, BlockDef]) -> FlowOut:
    o = out(f, FlowOut)
    o.dead = dead_blocks(f.graph, reg)
    return o


async def get(s: AsyncSession, flow_id: str) -> Flow:
    f = await s.get(Flow, flow_id)
    if f is None:
        raise ApplicationError("flow_not_found", 404)
    return f


async def listing(s: AsyncSession) -> list[FlowOut]:
    reg = await registry(s)
    return [view(f, reg) for f in (await s.scalars(select(Flow).order_by(Flow.name))).all()]


async def one(s: AsyncSession, flow_id: str) -> FlowOut:
    return view(await get(s, flow_id), await registry(s))


async def create(s: AsyncSession, p: Principal, data: FlowIn) -> FlowOut:
    p.need("admin")
    reg = await registry(s)
    graph = validate(data.graph or {"nodes": [], "edges": []}, reg)
    fid = data.id or slug(data.name, "flow")
    if await s.get(Flow, fid):
        fid = f"{fid}-{uuid.uuid4().hex[:4]}"
    f = Flow(
        id=fid,
        name=data.name,
        mode=data.mode if data.mode in MODES else "single",
        enabled=data.enabled,
        graph=graph,
        version=1,
        runs=0,
    )
    s.add(f)
    await s.flush()
    s.add(FlowVersion(flow_id=f.id, version=1, graph=graph, author=p.actor))
    await events.add(s, "flow.created", actor=p.actor, params={"name": f.name}, flow_id=f.id)
    return await _saved(s, f, reg)


async def update(s: AsyncSession, p: Principal, flow_id: str, data: FlowPatch) -> FlowOut:
    p.need("admin")
    f = await get(s, flow_id)
    reg = await registry(s)
    if not isinstance(data.graph, Unset):
        data.graph = validate(data.graph, reg)
    if not isinstance(data.mode, Unset) and data.mode not in MODES:
        raise ApplicationError("validation", 422, detail="mode")
    changed = patch(f, data)
    if "graph" in changed:
        f.version += 1
        s.add(FlowVersion(flow_id=f.id, version=f.version, graph=f.graph, author=p.actor))
        await events.add(s, "flow.saved", actor=p.actor, params={"name": f.name, "version": f.version}, flow_id=f.id)
    if "enabled" in changed:
        await events.add(
            s, "flow.enabled" if f.enabled else "flow.disabled", actor=p.actor, params={"name": f.name}, flow_id=f.id
        )
    return await _saved(s, f, reg)


async def _saved(s: AsyncSession, f: Flow, reg: dict[str, BlockDef]) -> FlowOut:
    snap = view(f, reg)
    after(s, lambda: realtime.emit("flow", snap, ["all", f"flow:{f.id}"]))
    after(s, lambda: tasks.kick("flows.reindex"))
    return snap


async def remove(s: AsyncSession, p: Principal, flow_id: str) -> None:
    p.need("admin")
    f = await get(s, flow_id)
    await events.add(s, "flow.removed", "warn", actor=p.actor, params={"name": f.name})
    await s.delete(f)
    after(s, lambda: realtime.emit("flow_gone", {"id": flow_id}, ["all"]))
    after(s, lambda: tasks.kick("flows.reindex"))


async def versions(s: AsyncSession, flow_id: str) -> list[VersionOut]:
    st = select(FlowVersion).where(FlowVersion.flow_id == flow_id).order_by(FlowVersion.version.desc()).limit(50)
    return [out(v, VersionOut) for v in (await s.scalars(st)).all()]


async def restore(s: AsyncSession, p: Principal, flow_id: str, version: int) -> FlowOut:
    v = await s.scalar(select(FlowVersion).where(FlowVersion.flow_id == flow_id, FlowVersion.version == version))
    if v is None:
        raise ApplicationError("not_found", 404)
    return await update(s, p, flow_id, FlowPatch(graph=v.graph))


async def runs(s: AsyncSession, flow_id: str, limit: int = 20, before: str | None = None) -> list[RunOut]:
    st = (
        select(FlowRun)
        .where(FlowRun.flow_id == flow_id, FlowRun.dry.is_(False))
        .order_by(FlowRun.started_at.desc(), FlowRun.id.desc())
        .limit(limit)
    )
    if cur := cursor(before):
        st = st.where(after_cursor(FlowRun.started_at, FlowRun.id, cur))
    return [out(r, RunOut) for r in (await s.scalars(st)).all()]


async def reindex(s: AsyncSession) -> int:
    reg = await registry(s)
    keys, filters = set(), set()
    for f in (await s.scalars(select(Flow).where(Flow.enabled.is_(True)))).all():
        if dead_blocks(f.graph, reg):
            continue
        for n in f.graph.get("nodes", []):
            b, p = reg.get(n.get("block")), n.get("params") or {}
            if b is None or b.kind != "trig":
                continue
            if b.key in ("state", "threshold"):
                keys.add(f"state:{p.get('device')}")
            elif b.key == "device_event":
                keys.add(f"action:{p.get('device')}")
            elif b.key in ("schedule", "sun"):
                keys.add("tick")
            elif b.key == "mqtt":
                keys.add("mqtt")
                filters.add(p.get("topic") or "#")
            elif b.key == "log_event":
                keys.add("log")
            elif b.key == "camera_event":
                keys.add(f"camera:{p.get('camera')}")
            elif b.ext:
                keys.add(f"ext:{b.ext}")
    for raw in (await kv().hgetall("flows:waits")).values():
        keys.add(f"wait:{json.loads(raw).get('device')}")
    pipe = kv().pipeline()
    pipe.delete("flows:trig", "flows:mqtt")
    if keys:
        pipe.sadd("flows:trig", *keys)
    if filters:
        pipe.sadd("flows:mqtt", *filters)
    await pipe.execute()
    await kv().publish("mqtt:index", "1")
    return len(keys)


def match(node: dict[str, Any], b: BlockDef, ev: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any] | None:
    p, t = node.get("params") or {}, ev.get("type")
    if t == "state" and ev.get("device") == p.get("device"):
        ch = ev.get("changes") or {}
        if b.key == "state" and p.get("cap") in ch:
            old, new = ch[p["cap"]]
            if p.get("to") not in (None, "") and not compare(new, "eq", p["to"]):
                return None
            if p.get("from") not in (None, "") and not compare(old, "eq", p["from"]):
                return None
            return {"v": new, "d": ev["device"], "c": p["cap"], "old": old}
        if b.key == "threshold" and p.get("cap") in ch:
            old, new = ch[p["cap"]]
            try:
                th, nv = float(p.get("value")), float(new)
            except TypeError, ValueError:
                return None
            ov = float(old) if isinstance(old, (int, float)) else None
            hit = (
                (ov is None or ov <= th) and nv > th if p.get("op") == "above" else (ov is None or ov >= th) and nv < th
            )
            return {"v": new, "d": ev["device"], "c": p["cap"], "old": old} if hit else None
        if b.key == "device_event" and "action" in ch:
            a = ch["action"][1]
            return {"v": a, "d": ev["device"]} if a and (not p.get("action") or a == p["action"]) else None
    if t == "tick":
        local = ctx["now"]
        if b.key == "schedule":
            try:
                return {"v": local.isoformat(timespec="minutes")} if cron_match(p.get("cron", ""), local) else None
            except ValueError:
                return None
        if b.key == "sun":
            mode, rise, sset = ctx["sun"]
            at = rise if p.get("event") == "sunrise" else sset
            if mode == "normal" and at is not None:
                at = at + timedelta(minutes=float(p.get("offset") or 0))
                hit = (at.hour, at.minute) == (local.hour, local.minute)
            else:
                f = hm(p.get("fallback") or ("08:00" if p.get("event") == "sunrise" else "16:00"))
                hit = (f.hour, f.minute) == (local.hour, local.minute)
            return {"v": p.get("event"), "polar": mode != "normal"} if hit else None
    if t == "mqtt" and b.key == "mqtt" and topic_matches_sub(p.get("topic") or "#", ev.get("topic", "")):
        return {"v": ev.get("payload"), "topic": ev.get("topic")}
    if t == "log" and b.key == "log_event" and not str(ev.get("event", "")).startswith("flow."):
        lv = events.LEVELS
        if fnmatch(ev.get("event", ""), p.get("pattern") or "*") and lv.get(ev.get("level"), 0) >= lv.get(
            p.get("level") or "info", 0
        ):
            tok = {"v": ev.get("params"), "e": ev.get("id"), "event": ev.get("event")}
            if ev.get("device"):
                tok["d"] = ev["device"]
                if isinstance(ev.get("params"), dict) and "cap" in ev["params"]:
                    tok["c"] = ev["params"]["cap"]
            return tok
    if t == "camera" and b.key == "camera_event" and ev.get("device") == p.get("camera"):
        phase = "start" if ev.get("phase") in ("start", "once") else "end"
        if p.get("label") not in (None, "") and ev.get("label") != p["label"]:
            return None
        if phase != (p.get("phase") or "start"):
            return None
        return {"v": ev.get("label"), "d": ev["device"], "label": ev.get("label"), "camera": ev.get("camera")}
    if t == "ext" and b.ext and node.get("block") == f"{ev.get('ext')}:{ev.get('key')}":
        pl = ev.get("payload")
        if isinstance(pl, dict) and any(pl.get(k) != v for k, v in p.items() if v not in (None, "") and k in pl):
            return None
        return {"v": pl}
    return None


async def dispatch(s: AsyncSession, ev: dict[str, Any]) -> int:
    if ev.get("type") == "state":
        await _waits(s, ev)
    home = await events.home(s)
    tz = zone(home.timezone)
    local = datetime.now(tz)
    ctx = {
        "now": local,
        "sun": sun(local.date(), home.lat, home.lon, tz) if ev.get("type") == "tick" else ("normal", None, None),
    }
    reg = await registry(s)
    started = 0
    for f in (await s.scalars(select(Flow).where(Flow.enabled.is_(True)))).all():
        if dead_blocks(f.graph, reg):
            continue
        for n in f.graph.get("nodes", []):
            b = reg.get(n.get("block"))
            if b is None or b.kind != "trig":
                continue
            tok = match(n, b, ev, ctx)
            if tok is not None:
                await start(s, f, n["id"], tok, cause=ev.get("cause") or ev.get("id"), reg=reg, home=home)
                started += 1
    return started


async def start(
    s: AsyncSession,
    f: Flow,
    node_id: str,
    tok: dict[str, Any],
    cause: int | None = None,
    dry: bool = False,
    graph: dict[str, Any] | None = None,
    reg: dict[str, BlockDef] | None = None,
    home: Any = None,
) -> dict[str, Any]:
    reg = reg or await registry(s)
    home = home or await events.home(s)
    key = f"flow:{f.id}:runs"
    if not dry:
        active = await kv().smembers(key)
        if active:
            if f.mode == "single":
                _log.info("flow_skip", flow=f.id, reason="single")
                return {"status": "skip"}
            if f.mode == "restart":
                for rid in active:
                    await cancel(s, rid)
            if f.mode == "queued":
                await kv().rpush(
                    f"flow:{f.id}:queue", json.dumps({"node": node_id, "tok": tok, "cause": cause}, default=str)
                )
                return {"status": "queued"}
            if f.mode == "parallel" and len(active) >= 10:
                return {"status": "skip"}
    run = None
    if not dry:
        run = FlowRun(flow_id=f.id, status="run", cause_id=cause, trace=[], ctx={"pending": 0}, started_at=now())
        s.add(run)
        await s.flush()
        await kv().sadd(key, str(run.id))
        f.runs += 1
    R = Run(s, f, run, dry, home, zone(home.timezone), cause, reg)
    b = reg.get(next((n.get("block") for n in (graph or f.graph).get("nodes", []) if n.get("id") == node_id), ""))
    R.note(
        node_id,
        "ok",
        "trigger",
        block=b.key if b else None,
        value=tok.get("v") if not isinstance(tok.get("v"), (dict, list)) else None,
    )
    await walk(R, graph or f.graph, [(node_id, 0, tok)])
    return await settle(R)


async def walk(R: Run, graph: dict[str, Any], starts: list[tuple[str, int | None, dict[str, Any]]]) -> None:
    nodes = {n["id"]: n for n in graph.get("nodes", [])}
    edges = graph.get("edges", [])
    q: deque[tuple[str, dict[str, Any]]] = deque()

    def follow(nid: str, port: int, tok: dict[str, Any]) -> bool:
        nxt = [e for e in edges if e.get("from") == nid and int(e.get("out", 0)) == port]
        for e in nxt:
            R.lit.add(f"{nid}>{e['to']}")
            q.append((e["to"], tok))
        return bool(nxt)

    for nid, port, tok in starts:
        if port is None:
            q.append((nid, tok))
        else:
            follow(nid, port, tok)
    while q:
        nid, tok = q.popleft()
        R.steps += 1
        if R.steps > 500:
            R.failed = True
            R.note(nid, "fail", "loop")
            break
        node = nodes.get(nid)
        if node is None:
            continue
        b = R.reg.get(node.get("block"))
        if b is None:
            R.failed = True
            R.note(nid, "fail", "dead", block=node.get("block"))
            continue
        try:
            res = await (_ext(R, node, b, tok) if b.ext else EXEC[b.key](R, node, node.get("params") or {}, tok))
        except ApplicationError as e:
            R.failed = True
            R.note(nid, "fail", "error", code=e.code, error=message(e.code, "en", **e.params))
            continue
        except Exception as e:
            _log.error("flow_node_failed", flow=R.flow.id, node=nid, block=b.key, error=str(e), exc_info=True)
            R.failed = True
            R.note(nid, "fail", "error", error=str(e)[:200])
            continue
        for port, t in res:
            if not follow(nid, port, t) and b.kind == "cond" and port == 1:
                R.stopped = True


async def _ext(R: Run, node: dict[str, Any], b: BlockDef, tok: dict[str, Any]) -> list[tuple[int, dict[str, Any]]]:
    params = dict(node.get("params") or {})
    for spec in b.params or []:
        k = spec.get("key")
        if spec.get("type") in ("text", "template") and isinstance(params.get(k), str):
            params[k] = await render(R, params[k], tok)
    if R.dry and b.kind == "act":
        R.note(node["id"], "skip", "dry_ext", block=b.key, text=params.get("text"))
        return [(0, tok)]
    res = await extensions.rpc(
        R.s,
        b.ext or "",
        "block",
        {
            "key": b.key.split(":", 1)[1],
            "params": params,
            "token": tok,
            "dry": R.dry,
            "flow": R.flow.id,
        },
    )
    tr = res.get("trace") or {}
    R.note(node["id"], tr.get("s", "ok"), tr.get("m", "ext"), **(tr.get("p") or {}))
    if b.kind == "act":
        R.acted = True
    return [(int(o[0]), {**tok, "v": o[1] if len(o) > 1 else tok.get("v")}) for o in res.get("outs", [[0]])]


async def settle(R: Run) -> dict[str, Any]:
    status = "fail" if R.failed else "wait" if R.pending > 0 else "stop" if R.stopped and not R.acted else "ok"
    result = {"status": status, "trace": R.trace, "lit": sorted(R.lit)}
    for rid in await kv().spop("flows:debounced", 100) or []:
        await cancel(R.s, rid, "stop")
    if R.dry or R.run is None:
        return result
    run, f = R.run, R.flow
    run.trace = [*run.trace, *R.trace]
    run.ctx = {**run.ctx, "pending": R.pending}
    run.status = status
    f.last_run_at, f.last_result = now(), status
    if status != "wait":
        run.finished_at = now()
        level = {"ok": "ok", "stop": "info", "fail": "crit"}.get(status, "info")
        await events.add(
            R.s, f"flow.{status}", level, actor=R.actor, params={"name": f.name}, flow_id=f.id, cause_id=R.cause
        )
        if status == "fail":
            await events.notify(R.s, f"flowfail:{f.id}", "warn", "flow_failed", {"name": f.name}, f"flows/{f.id}")
    snap = {"id": f.id, "lastResult": status, "lastRunAt": f.last_run_at.isoformat(), "runs": f.runs}
    run_snap = {"flow": f.id, "id": str(run.id), "status": status, "trace": run.trace, "lit": sorted(R.lit)}
    rid, done, queued = str(run.id), status != "wait", f.mode == "queued"

    async def push() -> None:
        if done:
            await kv().srem(f"flow:{f.id}:runs", rid)
            if queued and await kv().llen(f"flow:{f.id}:queue"):
                await tasks.kick("flows.queued", flow=f.id)
        await realtime.emit("flow_run", snap, ["all"])
        await realtime.emit("run", run_snap, [f"flow:{f.id}"])

    after(R.s, push)
    return result


async def cancel(s: AsyncSession, run_id: str, status: str = "cancel") -> None:
    try:
        run = await s.get(FlowRun, uuid.UUID(run_id))
    except ValueError:
        return
    if run is None or run.status not in ("run", "wait"):
        await kv().srem(f"flow:{run.flow_id}:runs" if run else "x", run_id)
        return
    run.status, run.finished_at = status, now()
    run.trace = [
        *run.trace,
        {
            "n": "",
            "s": "skip",
            "m": "cancelled" if status == "cancel" else "debounced",
            "p": {},
            "t": now().isoformat(timespec="seconds"),
        },
    ]
    fid = run.flow_id
    after(s, lambda: kv().srem(f"flow:{fid}:runs", run_id))


async def resume(s: AsyncSession, run_id: str, node: str, port: int, token: dict[str, Any]) -> dict[str, Any] | None:
    try:
        run = await s.get(FlowRun, uuid.UUID(run_id), with_for_update=True)
    except ValueError:
        return None
    if run is None or run.status != "wait":
        return None
    f = await s.get(Flow, run.flow_id)
    if f is None:
        return None
    home = await events.home(s)
    R = Run(s, f, run, False, home, zone(home.timezone), run.cause_id, await registry(s))
    R.pending = max(int(run.ctx.get("pending", 1)) - 1, 0)
    R.note(node, "ok", "resumed", port=port)
    await walk(R, f.graph, [(node, port, token)])
    return await settle(R)


async def _waits(s: AsyncSession, ev: dict[str, Any]) -> None:
    waits = await kv().hgetall("flows:waits")
    if not waits:
        return
    ch = ev.get("changes") or {}
    for key, raw in waits.items():
        w = json.loads(raw)
        if w.get("device") != ev.get("device") or w.get("cap") not in ch:
            continue
        if w.get("to") not in (None, "") and not compare(ch[w["cap"]][1], "eq", w["to"]):
            continue
        if not await kv().hdel("flows:waits", key):
            continue
        await tasks.cancel(f"wait:{key}")
        await resume(s, w["run"], w["node"], 0, w.get("token") or {})
    after(s, lambda: tasks.kick("flows.reindex"))


async def wait_timeout(s: AsyncSession, run_id: str, node: str) -> None:
    key = f"{run_id}:{node}"
    raw = await kv().hget("flows:waits", key)
    if not raw or not await kv().hdel("flows:waits", key):
        return
    await resume(s, run_id, node, 1, json.loads(raw).get("token") or {})
    after(s, lambda: tasks.kick("flows.reindex"))


async def queued(s: AsyncSession, flow_id: str) -> None:
    raw = await kv().lpop(f"flow:{flow_id}:queue")
    f = await s.get(Flow, flow_id)
    if raw and f:
        item = json.loads(raw)
        await start(s, f, item["node"], item["tok"], cause=item.get("cause"))


async def manual(s: AsyncSession, p: Principal, flow_id: str) -> dict[str, Any]:
    p.need("member")
    f = await get(s, flow_id)
    reg = await registry(s)
    if dead := dead_blocks(f.graph, reg):
        raise ApplicationError("flow_dead", 409, block=dead[0])
    trig = next((n for n in f.graph.get("nodes", []) if n.get("block") == "manual"), None) or next(
        (n for n in f.graph.get("nodes", []) if (b := reg.get(n.get("block"))) and b.kind == "trig"), None
    )
    if trig is None:
        raise ApplicationError("flow_invalid", 422, detail="trigger")
    ev = await events.add(s, "flow.manual", actor=p.actor, params={"name": f.name}, flow_id=f.id)
    return await start(s, f, trig["id"], {"v": None, "manual": True}, cause=ev.id, reg=reg)


async def test(s: AsyncSession, p: Principal, flow_id: str, data: TestIn) -> dict[str, Any]:
    p.need("member")
    f = await get(s, flow_id)
    reg = await registry(s)
    graph = validate(data.graph, reg) if data.graph else f.graph
    if dead := dead_blocks(graph, reg):
        raise ApplicationError("flow_dead", 409, block=dead[0])
    nodes = graph.get("nodes", [])
    trig = next((n for n in nodes if n.get("id") == data.node), None) or next(
        (n for n in nodes if (b := reg.get(n.get("block"))) and b.kind == "trig"), None
    )
    if trig is None:
        raise ApplicationError("flow_invalid", 422, detail="trigger")
    tok = await _sample(s, trig)
    return await start(s, f, trig["id"], tok, dry=True, graph=graph, reg=reg)


async def _sample(s: AsyncSession, node: dict[str, Any]) -> dict[str, Any]:
    from app.db.models import Device

    p = node.get("params") or {}
    d = await s.get(Device, p.get("device", "")) if p.get("device") else None
    v = d.state.get(p.get("cap", "")) if d else None
    if node.get("block") == "state" and p.get("to") not in (None, ""):
        v = p["to"]
    return {"v": v, "d": p.get("device"), "c": p.get("cap"), "dry": True}


async def stats(s: AsyncSession) -> dict[str, int]:
    rows = (
        await s.execute(
            select(FlowRun.status, func.count())
            .where(FlowRun.started_at >= func.date_trunc("day", func.now()))
            .group_by(FlowRun.status)
        )
    ).all()
    return {st: n for st, n in rows}
