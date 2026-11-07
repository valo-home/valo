import ast
import json
import operator as op
import re
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select

from app.db.base import after
from app.db.models import Device, Room
from app.domain import devices, events, scenes
from app.domain.common import Principal, S
from app.lib import mqtt, tasks
from app.lib.kv import kv
from app.lib.timeutil import hm, in_window

Out = list[tuple[int, dict[str, Any]]]


class BlockDef(S):
    key: str
    kind: str
    ins: list[str]
    outs: list[str]
    labels: list[str] = []
    params: list[dict[str, Any]] = []
    ext: str | None = None
    name: dict[str, str] | None = None
    icon: str | None = None


def P(key: str, type: str, required: bool = True, **kw: Any) -> dict[str, Any]:
    return {"key": key, "type": type, "required": required, **kw}


EV = ["ev"]
YN = ["ev", "ev"]
BUILTIN = [
    BlockDef(
        "state",
        "trig",
        [],
        EV,
        params=[P("device", "device"), P("cap", "cap"), P("to", "value", False), P("from", "value", False)],
    ),
    BlockDef(
        "threshold",
        "trig",
        [],
        EV,
        params=[
            P("device", "device"),
            P("cap", "cap"),
            P("op", "select", options=["above", "below"]),
            P("value", "number"),
        ],
    ),
    BlockDef("device_event", "trig", [], EV, params=[P("device", "device"), P("action", "text", False)]),
    BlockDef("schedule", "trig", [], EV, params=[P("cron", "cron", default="0 7 * * 1-5")]),
    BlockDef(
        "sun",
        "trig",
        [],
        EV,
        params=[
            P("event", "select", options=["sunrise", "sunset"]),
            P("offset", "number", False, default=0),
            P("fallback", "time", False, default="16:00"),
        ],
    ),
    BlockDef("mqtt", "trig", [], EV, params=[P("topic", "topic")]),
    BlockDef(
        "camera_event",
        "trig",
        [],
        EV,
        params=[
            P("camera", "camera"),
            P("label", "select", False, options=["motion", "person", "car", "animal"], default="motion"),
            P("phase", "select", False, options=["start", "end"], default="start"),
        ],
    ),
    BlockDef("manual", "trig", [], EV),
    BlockDef(
        "log_event",
        "trig",
        [],
        EV,
        params=[
            P("pattern", "text", default="device.offline"),
            P("level", "select", False, options=["info", "warn", "crit"]),
        ],
    ),
    BlockDef(
        "compare",
        "cond",
        EV,
        YN,
        ["yes", "no"],
        [
            P("device", "device"),
            P("cap", "cap"),
            P("op", "select", options=["eq", "ne", "lt", "le", "gt", "ge"]),
            P("value", "value"),
        ],
    ),
    BlockDef("time_window", "cond", EV, YN, ["yes", "no"], [P("from", "time"), P("to", "time")]),
    BlockDef("weekday", "cond", EV, YN, ["yes", "no"], [P("days", "days", default=[1, 2, 3, 4, 5])]),
    BlockDef(
        "state_for",
        "cond",
        EV,
        YN,
        ["yes", "no"],
        [
            P("device", "device"),
            P("cap", "cap"),
            P("op", "select", options=["eq", "ne", "lt", "le", "gt", "ge"]),
            P("value", "value"),
            P("minutes", "number", default=10),
        ],
    ),
    BlockDef("expr", "cond", EV, YN, ["yes", "no"], [P("expr", "text", default='state("device", "cap") > 0')]),
    BlockDef("available", "cond", EV, YN, ["yes", "no"], [P("device", "device", False)]),
    BlockDef(
        "branch",
        "logic",
        EV,
        ["ev", "ev", "ev"],
        ["case1", "case2", "else"],
        [P("device", "device"), P("cap", "cap"), P("values", "list")],
    ),
    BlockDef("delay", "logic", EV, EV, params=[P("seconds", "duration", default=60)]),
    BlockDef(
        "wait",
        "logic",
        EV,
        YN,
        ["ok", "timeout"],
        [P("device", "device"), P("cap", "cap"), P("to", "value", False), P("timeout", "duration", default=300)],
    ),
    BlockDef("debounce", "logic", EV, EV, params=[P("seconds", "duration", default=30)]),
    BlockDef("counter", "logic", EV, EV, params=[P("count", "number", default=3), P("window", "number", default=10)]),
    BlockDef("command", "act", EV, EV, params=[P("device", "device"), P("values", "values")]),
    BlockDef("scene", "act", EV, EV, params=[P("scene", "scene")]),
    BlockDef(
        "notify",
        "act",
        EV,
        EV,
        params=[
            P("text", "text"),
            P("level", "select", False, options=["info", "warn", "crit"], default="info"),
            P("push", "bool", False, default=False),
        ],
    ),
    BlockDef(
        "publish",
        "act",
        EV,
        EV,
        params=[P("topic", "topic"), P("payload", "text", False), P("retain", "bool", False, default=False)],
    ),
    BlockDef("log", "act", EV, EV, params=[P("text", "text")]),
    BlockDef("snapshot", "act", EV, EV, params=[P("camera", "camera", False)]),
    BlockDef("clip", "act", EV, EV, params=[P("camera", "camera", False), P("seconds", "duration", False, default=30)]),
    BlockDef(
        "camera_set",
        "act",
        EV,
        EV,
        params=[
            P("camera", "camera", False),
            P("setting", "select", options=["privacy", "motion", "daynight", "record", "detect"], default="privacy"),
            P("value", "select", options=["on", "off", "auto", "day", "night", "events", "continuous"], default="on"),
        ],
    ),
    BlockDef("camera_reboot", "act", EV, EV, params=[P("camera", "camera", False)]),
    BlockDef("ptz_preset", "act", EV, EV, params=[P("camera", "camera", False), P("preset", "text")]),
    BlockDef(
        "ptz_patrol",
        "act",
        EV,
        EV,
        params=[
            P("camera", "camera", False),
            P("presets", "list"),
            P("seconds", "duration", False, default=20),
            P("rounds", "number", False, default=1),
        ],
    ),
    BlockDef("math", "xf", ["any"], ["n"], params=[P("expr", "text", default="value * 1")]),
]
BLOCKS = {b.key: b for b in BUILTIN}
_CMP = {"eq": op.eq, "ne": op.ne, "lt": op.lt, "le": op.le, "gt": op.gt, "ge": op.ge}
_BIN = {ast.Add: op.add, ast.Sub: op.sub, ast.Mult: op.mul, ast.Div: op.truediv, ast.Mod: op.mod}
_AST_CMP = {ast.Eq: op.eq, ast.NotEq: op.ne, ast.Lt: op.lt, ast.LtE: op.le, ast.Gt: op.gt, ast.GtE: op.ge}


def coerce(target: Any, sample: Any) -> Any:
    if isinstance(sample, bool):
        return target if isinstance(target, bool) else str(target).lower() in ("true", "1", "on", "yes")
    if isinstance(sample, (int, float)):
        try:
            return float(target)
        except TypeError, ValueError:
            return target
    return target


def compare(v: Any, o: str, target: Any) -> bool:
    if v is None:
        return o == "ne"
    try:
        return _CMP[o](v, coerce(target, v))
    except TypeError:
        return False


def evaluate(expr: str, names: dict[str, Any], funcs: dict[str, Callable[..., Any]]) -> Any:
    def ev(n: ast.AST) -> Any:
        match n:
            case ast.Expression():
                return ev(n.body)
            case ast.Constant():
                return n.value
            case ast.Name() if n.id in names:
                return names[n.id]
            case ast.BoolOp():
                if isinstance(n.op, ast.And):
                    return all(ev(x) for x in n.values)
                return any(ev(x) for x in n.values)
            case ast.UnaryOp(op=ast.Not()):
                return not ev(n.operand)
            case ast.UnaryOp(op=ast.USub()):
                return -ev(n.operand)
            case ast.BinOp() if type(n.op) in _BIN:
                return _BIN[type(n.op)](ev(n.left), ev(n.right))
            case ast.Compare():
                left = ev(n.left)
                for o, right in zip(n.ops, n.comparators, strict=True):
                    r = ev(right)
                    if left is None or r is None or not _AST_CMP[type(o)](left, r):
                        return False
                    left = r
                return True
            case ast.IfExp():
                return ev(n.body) if ev(n.test) else ev(n.orelse)
            case ast.Call(func=ast.Name(id=fid)) if fid in funcs and not n.keywords:
                return funcs[fid](*[ev(a) for a in n.args])
        raise ValueError(ast.dump(n)[:80])

    return ev(ast.parse(expr, mode="eval"))


class Run:
    def __init__(self, s, flow, run, dry: bool, home, tz, cause: int | None, reg: dict[str, BlockDef]) -> None:
        self.s, self.flow, self.run, self.dry, self.home, self.tz, self.cause, self.reg = (
            s,
            flow,
            run,
            dry,
            home,
            tz,
            cause,
            reg,
        )
        self.p = Principal(id=f"flow:{flow.id}", username=f"flow:{flow.id}", name=flow.name, role="owner")
        self.actor = f"flow:{flow.id}"
        self.trace: list[dict[str, Any]] = []
        self.lit: set[str] = set()
        self.pending, self.acted, self.stopped, self.failed, self.steps = 0, False, False, False, 0
        self._devs: dict[str, Device | None] = {}
        self._states: dict[str, dict[str, Any]] | None = None
        self._all: list[Device] | None = None

    @property
    def rid(self) -> str:
        return str(self.run.id) if self.run is not None else "dry"

    def now(self) -> datetime:
        return datetime.now(self.tz)

    def note(self, nid: str, status: str, code: str, /, **params: Any) -> None:
        self.trace.append(
            {
                "n": nid,
                "s": status,
                "m": code,
                "p": {k: v for k, v in params.items() if v is not None},
                "t": self.now().isoformat(timespec="seconds"),
            }
        )

    async def dev(self, did: str) -> Device | None:
        if did not in self._devs:
            self._devs[did] = await self.s.get(Device, did)
        return self._devs[did]

    async def states(self) -> dict[str, dict[str, Any]]:
        if self._states is None:
            self._states = {d.id: d.state for d in (await self.s.scalars(select(Device))).all()}
        return self._states

    async def all_devices(self) -> list[Device]:
        if self._all is None:
            self._all = list((await self.s.scalars(select(Device).order_by(Device.name))).all())
        return self._all

    async def lists(self) -> dict[str, list[Device]]:
        ds = [d for d in await self.all_devices() if not d.disabled]
        return {
            "low_battery": [d for d in ds if isinstance(d.state.get("bat"), (int, float)) and d.state["bat"] < 15],
            "offline": [d for d in ds if not d.available],
            "alarms": [d for d in ds if any(d.state.get(k) is True for k in ALARM_CAPS)],
        }

    async def calc(self, expr: str, value: Any = None) -> Any:
        st = await self.states()
        now = self.now()
        ls = await self.lists() if re.search(r"\b(low_battery|offline|alarms)\(", expr) else {}
        funcs = {
            "state": lambda d, c: st.get(d, {}).get(c),
            "min": min,
            "max": max,
            "abs": abs,
            "round": round,
            "low_battery": lambda: len(ls.get("low_battery", [])),
            "offline": lambda: len(ls.get("offline", [])),
            "alarms": lambda: len(ls.get("alarms", [])),
        }
        return evaluate(
            expr,
            {
                "value": value,
                "hour": now.hour,
                "minute": now.minute,
                "weekday": now.isoweekday(),
                "True": True,
                "False": False,
                "None": None,
            },
            funcs,
        )


ALARM_CAPS = ("leak", "smoke", "co", "gas")
_VAR = re.compile(r"\{(\w+)\}")
_WORDS = {
    "uk": ("так", "ні", "немає"),
    "ru": ("да", "нет", "нет"),
    "en": ("yes", "no", "none"),
}


def fmt_value(v: Any, lang: str) -> str:
    yes, no, _ = _WORDS.get(lang, _WORDS["en"])
    if isinstance(v, bool):
        return yes if v else no
    if isinstance(v, float):
        return f"{v:.2f}".rstrip("0").rstrip(".")
    if v is None:
        return "-"
    if isinstance(v, dict):
        return ", ".join(f"{k} {fmt_value(x, lang)}" for k, x in v.items())
    return str(v)


async def render(R: Run, text: str, tok: dict[str, Any]) -> str:
    if not text or "{" not in text:
        return text
    wanted = set(_VAR.findall(text))
    if not wanted:
        return text
    lang = str((R.home.settings or {}).get("lang") or "uk")
    none = _WORDS.get(lang, _WORDS["en"])[2]
    now = R.now()
    v = tok.get("v")
    did = tok.get("d") or ""
    d = await R.dev(did) if did else None
    cap = tok.get("c") or (v.get("cap") if isinstance(v, dict) else None)
    if isinstance(v, dict) and "value" in v and cap:
        v = v["value"]
    unit = ""
    if d is not None and cap:
        unit = next((c.get("unit") or "" for c in d.caps if c.get("id") == cap), "")
    room = None
    if d is not None and d.room_id:
        r = await R.s.get(Room, d.room_id)
        room = r.name if r else None
    ctx: dict[str, Any] = {
        "name": d.name if d else (tok.get("v") or {}).get("name") if isinstance(tok.get("v"), dict) else None,
        "device": d.name if d else None,
        "room": room,
        "cap": cap,
        "value": fmt_value(v, lang) if not isinstance(v, dict) else None,
        "old": fmt_value(tok["old"], lang) if "old" in tok else None,
        "unit": unit,
        "time": now.strftime("%H:%M"),
        "date": now.strftime("%d.%m.%Y"),
        "flow": R.flow.name,
        "home": R.home.name,
        "event": tok.get("event"),
        "label": tok.get("label"),
        "snapshot": tok.get("snapshot"),
        "clip": tok.get("clip"),
    }
    if isinstance(tok.get("v"), dict):
        for k, x in tok["v"].items():
            if ctx.get(k) is None:
                ctx[k] = fmt_value(x, lang)
    if wanted & {"low_battery", "offline", "alarms"}:
        ls = await R.lists()
        ctx["low_battery"] = ", ".join(f"{x.name} ({x.state['bat']}%)" for x in ls["low_battery"]) or none
        ctx["offline"] = ", ".join(x.name for x in ls["offline"]) or none
        ctx["alarms"] = ", ".join(x.name for x in ls["alarms"]) or none
    return _VAR.sub(lambda m: str(ctx[m.group(1)]) if ctx.get(m.group(1)) is not None else m.group(0), text)


def name_of(d: Device | None, did: str) -> str:
    return d.name if d else did


async def x_compare(R: Run, n: dict, p: dict, t: dict) -> Out:
    d = await R.dev(p.get("device", ""))
    v = d.state.get(p.get("cap", "")) if d else None
    ok = compare(v, p.get("op", "eq"), p.get("value"))
    R.note(
        n["id"],
        "ok" if ok else "no",
        "compare",
        name=name_of(d, p.get("device", "")),
        cap=p.get("cap"),
        value=v,
        op=p.get("op"),
        target=p.get("value"),
    )
    return [(0 if ok else 1, t)]


async def x_time_window(R: Run, n: dict, p: dict, t: dict) -> Out:
    now = R.now()
    ok = in_window(now.time(), hm(p.get("from", "00:00")), hm(p.get("to", "23:59")))
    R.note(
        n["id"], "ok" if ok else "no", "time_window", now=now.strftime("%H:%M"), start=p.get("from"), end=p.get("to")
    )
    return [(0 if ok else 1, t)]


async def x_weekday(R: Run, n: dict, p: dict, t: dict) -> Out:
    wd = R.now().isoweekday()
    ok = wd in (p.get("days") or [])
    R.note(n["id"], "ok" if ok else "no", "weekday", day=wd)
    return [(0 if ok else 1, t)]


async def x_state_for(R: Run, n: dict, p: dict, t: dict) -> Out:
    d = await R.dev(p.get("device", ""))
    cap = p.get("cap", "")
    v = d.state.get(cap) if d else None
    since = (d.attrs.get("changed") or {}).get(cap) if d else None
    held = (R.now() - datetime.fromisoformat(since)).total_seconds() / 60 if since else 1e9
    ok = compare(v, p.get("op", "eq"), p.get("value")) and held >= float(p.get("minutes") or 0)
    R.note(
        n["id"],
        "ok" if ok else "no",
        "state_for",
        name=name_of(d, p.get("device", "")),
        cap=cap,
        value=v,
        minutes=round(held) if held < 1e8 else None,
    )
    return [(0 if ok else 1, t)]


async def x_expr(R: Run, n: dict, p: dict, t: dict) -> Out:
    ok = bool(await R.calc(p.get("expr") or "False", t.get("v")))
    R.note(n["id"], "ok" if ok else "no", "expr", expr=p.get("expr"))
    return [(0 if ok else 1, t)]


async def x_branch(R: Run, n: dict, p: dict, t: dict) -> Out:
    d = await R.dev(p.get("device", ""))
    v = d.state.get(p.get("cap", "")) if d else None
    vals = [str(x) for x in p.get("values") or []][:2]
    i = vals.index(str(v)) if str(v) in vals else 2
    R.note(n["id"], "ok", "branch", value=v, port=i)
    return [(i, t)]


async def suspend(R: Run, n: dict, delay: float, port: int, t: dict, key: str | None = None) -> None:
    R.pending += 1
    await tasks.later(
        key or f"run:{R.rid}:{n['id']}:{port}",
        max(delay, 0.1),
        "flows.resume",
        run=R.rid,
        node=n["id"],
        port=port,
        token=t,
    )


async def x_delay(R: Run, n: dict, p: dict, t: dict) -> Out:
    sec = float(p.get("seconds") or 0)
    if R.dry:
        R.note(n["id"], "skip", "dry_delay", seconds=sec)
        return [(0, t)]
    until = R.now() + timedelta(seconds=sec)
    await suspend(R, n, sec, 0, t)
    R.note(n["id"], "wait", "delay", until=until.strftime("%H:%M:%S"))
    return []


async def x_wait(R: Run, n: dict, p: dict, t: dict) -> Out:
    if R.dry:
        R.note(n["id"], "skip", "dry_wait")
        return [(0, t)]
    did, rid = p.get("device", ""), R.rid
    key = f"{rid}:{n['id']}"
    await kv().hset(
        "flows:waits",
        key,
        json.dumps(
            {
                "flow": R.flow.id,
                "run": rid,
                "node": n["id"],
                "device": did,
                "cap": p.get("cap"),
                "to": p.get("to"),
                "token": t,
            }
        ),
    )
    await kv().sadd("flows:trig", f"wait:{did}")
    R.pending += 1
    await tasks.later(f"wait:{key}", float(p.get("timeout") or 300), "flows.wait_timeout", run=rid, node=n["id"])
    d = await R.dev(did)
    R.note(n["id"], "wait", "wait", name=name_of(d, did), cap=p.get("cap"), to=p.get("to"))
    return []


async def x_debounce(R: Run, n: dict, p: dict, t: dict) -> Out:
    sec = float(p.get("seconds") or 0)
    if R.dry:
        R.note(n["id"], "skip", "dry_delay", seconds=sec)
        return [(0, t)]
    slot = f"deb:{R.flow.id}:{n['id']}"
    prev = await kv().getset(slot, R.rid)
    if prev and prev != R.rid:
        await kv().sadd("flows:debounced", prev)
    await suspend(R, n, sec, 0, t, key=slot)
    R.note(n["id"], "wait", "debounce", seconds=sec)
    return []


async def x_counter(R: Run, n: dict, p: dict, t: dict) -> Out:
    need = int(p.get("count") or 1)
    key = f"cnt:{R.flow.id}:{n['id']}"
    if R.dry:
        cur = int(await kv().get(key) or 0) + 1
    else:
        cur = await kv().incr(key)
        if cur == 1:
            await kv().expire(key, int(float(p.get("window") or 10) * 60))
        if cur >= need:
            await kv().delete(key)
    ok = cur >= need
    R.note(n["id"], "ok" if ok else "no", "counter", n=cur, count=need)
    return [(0, t)] if ok else []


async def x_command(R: Run, n: dict, p: dict, t: dict) -> Out:
    did, values = p.get("device", ""), dict(p.get("values") or {})
    d = await R.dev(did)
    if R.dry:
        R.note(n["id"], "skip", "dry_command", name=name_of(d, did), values=values)
        return [(0, t)]
    await devices.command(R.s, R.p, did, values, actor=R.actor, cause_id=R.cause)
    R.acted = True
    R.note(n["id"], "ok", "command", name=name_of(d, did), values=values)
    return [(0, t)]


async def x_scene(R: Run, n: dict, p: dict, t: dict) -> Out:
    sc = await scenes.get(R.s, p.get("scene", ""))
    if R.dry:
        R.note(n["id"], "skip", "dry_scene", name=sc.name)
        return [(0, t)]
    await scenes.apply(R.s, R.p, sc.id, actor=R.actor, cause_id=R.cause)
    R.acted = True
    R.note(n["id"], "ok", "scene", name=sc.name)
    return [(0, t)]


async def x_available(R: Run, n: dict, p: dict, t: dict) -> Out:
    did = p.get("device") or t.get("d") or ""
    d = await R.dev(did) if did else None
    ok = bool(d and d.available)
    R.note(n["id"], "ok" if ok else "no", "available", name=name_of(d, did), value=ok)
    return [(0 if ok else 1, t)]


async def x_notify(R: Run, n: dict, p: dict, t: dict) -> Out:
    text, level = await render(R, str(p.get("text") or ""), t), p.get("level") or "info"
    if R.dry:
        R.note(n["id"], "skip", "dry_notify", text=text)
        return [(0, t)]
    await events.notify(
        R.s,
        f"flow:{R.flow.id}:{n['id']}",
        level,
        "flow_notify",
        {"text": text, "flow": R.flow.name},
        f"flows/{R.flow.id}",
        force=bool(p.get("push")),
    )
    R.acted = True
    R.note(n["id"], "ok", "notify", text=text, push=bool(p.get("push")))
    return [(0, t)]


async def x_publish(R: Run, n: dict, p: dict, t: dict) -> Out:
    topic, payload = p.get("topic", ""), p.get("payload", "")
    if R.dry:
        R.note(n["id"], "skip", "dry_publish", topic=topic)
        return [(0, t)]
    after(R.s, lambda: mqtt.publish(topic, payload, qos=1, retain=bool(p.get("retain"))))
    R.acted = True
    R.note(n["id"], "ok", "publish", topic=topic)
    return [(0, t)]


async def x_log(R: Run, n: dict, p: dict, t: dict) -> Out:
    text = str(p.get("text") or "")
    if not R.dry:
        await events.add(
            R.s,
            "flow.log",
            actor=R.actor,
            params={"text": text, "name": R.flow.name},
            flow_id=R.flow.id,
            cause_id=R.cause,
        )
        R.acted = True
    R.note(n["id"], "skip" if R.dry else "ok", "log", text=text)
    return [(0, t)]


async def _camera_of(R: Run, p: dict, t: dict) -> tuple[str, Device | None]:
    from app.db.models import Camera

    did = p.get("camera") or t.get("d") or ""
    d = await R.dev(did) if did else None
    cid = await R.s.scalar(select(Camera.id).where(Camera.device_id == did)) if did else None
    return cid or "", d


async def x_snapshot(R: Run, n: dict, p: dict, t: dict) -> Out:
    from app.domain import cameras
    from app.lib.errors import ApplicationError

    cid, d = await _camera_of(R, p, t)
    if not cid:
        R.note(n["id"], "fail", "no_camera")
        return [(0, t)]
    if R.dry:
        R.note(n["id"], "skip", "dry_snapshot", name=name_of(d, cid))
        return [(0, t)]
    try:
        m = await cameras.capture(R.s, cid, R.actor, label="flow")
    except ApplicationError as e:
        R.note(n["id"], "fail", "snapshot_failed", name=name_of(d, cid), code=e.code)
        return [(0, t)]
    R.acted = True
    url = f"/api/v1/media/{m.id}/file"
    R.note(n["id"], "ok", "snapshot", name=name_of(d, cid))
    return [(0, {**t, "snapshot": url, "media": str(m.id)})]


async def x_clip(R: Run, n: dict, p: dict, t: dict) -> Out:
    from app.domain import cameras
    from app.lib.errors import ApplicationError

    cid, d = await _camera_of(R, p, t)
    seconds = int(p.get("seconds") or 30)
    if not cid:
        R.note(n["id"], "fail", "no_camera")
        return [(0, t)]
    if R.dry:
        R.note(n["id"], "skip", "dry_clip", name=name_of(d, cid), n=seconds)
        return [(0, t)]
    try:
        await cameras.clip(R.s, None, cid, seconds, R.actor)
    except ApplicationError as e:
        R.note(n["id"], "fail", "clip_failed", name=name_of(d, cid), code=e.code)
        return [(0, t)]
    R.acted = True
    R.note(n["id"], "ok", "clip", name=name_of(d, cid), n=seconds)
    return [(0, t)]


CAMERA_SET = {
    "privacy": {"on": ("privacy", True), "off": ("privacy", False)},
    "motion": {"on": ("motion_enabled", True), "off": ("motion_enabled", False)},
    "daynight": {v: ("daynight_mode", v) for v in ("auto", "day", "night")},
}


async def x_camera_set(R: Run, n: dict, p: dict, t: dict) -> Out:
    from app.domain import cameras
    from app.lib.errors import ApplicationError

    cid, d = await _camera_of(R, p, t)
    setting, value = str(p.get("setting") or ""), str(p.get("value") or "")
    if not cid:
        R.note(n["id"], "fail", "no_camera")
        return [(0, t)]
    pair = CAMERA_SET.get(setting, {}).get(value)
    if setting == "record" and value in ("off", "events", "continuous"):
        pair = ("record", value)
    if setting == "detect" and value in ("on", "off"):
        pair = ("detect", value == "on")
    if pair is None:
        R.note(n["id"], "fail", "camera_set_invalid", name=name_of(d, cid), setting=setting, value=value)
        return [(0, t)]
    if R.dry:
        R.note(n["id"], "skip", "dry_camera_set", name=name_of(d, cid), setting=setting, value=value)
        return [(0, t)]
    try:
        if pair[0] == "record":
            await cameras.update(R.s, R.p, cid, cameras.CameraPatch(record={"mode": pair[1]}))
            failed: dict[str, str] = {}
        elif pair[0] == "detect":
            await cameras.update(R.s, R.p, cid, cameras.CameraPatch(record={"detect": {"enabled": pair[1]}}))
            failed = {}
        else:
            failed = (await cameras.settings_set(R.s, R.p, cid, {pair[0]: pair[1]}))["failed"]
    except ApplicationError as e:
        R.note(n["id"], "fail", "camera_set_failed", name=name_of(d, cid), setting=setting, code=e.code)
        return [(0, t)]
    if failed:
        R.note(
            n["id"],
            "fail",
            "camera_set_failed",
            name=name_of(d, cid),
            setting=setting,
            code=next(iter(failed.values())),
        )
        return [(0, t)]
    R.acted = True
    R.note(n["id"], "ok", "camera_set", name=name_of(d, cid), setting=setting, value=value)
    return [(0, t)]


async def x_camera_reboot(R: Run, n: dict, p: dict, t: dict) -> Out:
    from app.domain import cameras
    from app.lib.errors import ApplicationError

    cid, d = await _camera_of(R, p, t)
    if not cid:
        R.note(n["id"], "fail", "no_camera")
        return [(0, t)]
    if R.dry:
        R.note(n["id"], "skip", "dry_camera_reboot", name=name_of(d, cid))
        return [(0, t)]
    try:
        await cameras.action(R.s, R.p, cid, "reboot", {})
    except ApplicationError as e:
        R.note(n["id"], "fail", "camera_reboot_failed", name=name_of(d, cid), code=e.code)
        return [(0, t)]
    R.acted = True
    R.note(n["id"], "ok", "camera_reboot", name=name_of(d, cid))
    return [(0, t)]


async def x_ptz_preset(R: Run, n: dict, p: dict, t: dict) -> Out:
    from app.domain import cameras
    from app.lib.errors import ApplicationError

    cid, d = await _camera_of(R, p, t)
    preset = (await render(R, str(p.get("preset") or ""), t)).strip()
    if not cid or not preset:
        R.note(n["id"], "fail", "no_camera")
        return [(0, t)]
    if R.dry:
        R.note(n["id"], "skip", "dry_ptz_preset", name=name_of(d, cid), preset=preset)
        return [(0, t)]
    try:
        await cameras.preset_go(R.s, R.p, cid, preset)
    except ApplicationError as e:
        R.note(n["id"], "fail", "ptz_failed", name=name_of(d, cid), code=e.code)
        return [(0, t)]
    R.acted = True
    R.note(n["id"], "ok", "ptz_preset", name=name_of(d, cid), preset=preset)
    return [(0, t)]


async def x_ptz_patrol(R: Run, n: dict, p: dict, t: dict) -> Out:
    from app.lib import tasks

    cid, d = await _camera_of(R, p, t)
    presets = [str(x).strip() for x in (p.get("presets") or []) if str(x).strip()][:16]
    seconds = max(5, min(int(p.get("seconds") or 20), 3600))
    rounds = max(1, min(int(p.get("rounds") or 1), 100))
    if not cid or not presets:
        R.note(n["id"], "fail", "no_camera")
        return [(0, t)]
    if R.dry:
        R.note(n["id"], "skip", "dry_ptz_patrol", name=name_of(d, cid), n=len(presets))
        return [(0, t)]

    async def go() -> None:
        await tasks.kick("cameras.patrol", camera=cid, presets=presets, seconds=seconds, rounds=rounds)

    after(R.s, go)
    R.acted = True
    R.note(n["id"], "ok", "ptz_patrol", name=name_of(d, cid), n=len(presets))
    return [(0, t)]


async def x_math(R: Run, n: dict, p: dict, t: dict) -> Out:
    v = await R.calc(p.get("expr") or "value", t.get("v"))
    R.note(n["id"], "ok", "math", value=v)
    return [(0, {**t, "v": v})]


EXEC: dict[str, Callable[[Run, dict, dict, dict], Awaitable[Out]]] = {
    "compare": x_compare,
    "available": x_available,
    "time_window": x_time_window,
    "weekday": x_weekday,
    "state_for": x_state_for,
    "expr": x_expr,
    "branch": x_branch,
    "delay": x_delay,
    "wait": x_wait,
    "debounce": x_debounce,
    "counter": x_counter,
    "command": x_command,
    "scene": x_scene,
    "notify": x_notify,
    "publish": x_publish,
    "log": x_log,
    "snapshot": x_snapshot,
    "clip": x_clip,
    "camera_set": x_camera_set,
    "camera_reboot": x_camera_reboot,
    "ptz_preset": x_ptz_preset,
    "ptz_patrol": x_ptz_patrol,
    "math": x_math,
}
