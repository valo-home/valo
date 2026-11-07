import asyncio
import json
import time
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import timerlogic as tl
from valo_sdk import Extension

ext = Extension()
STATE = ext.data / "state.json"
TICK = 1
CAL_EVERY = 300
REJECTED: list[str] = []
TIMERS = tl.parse_timers(str(ext.settings.get("timers") or ""), REJECTED)
ALARMS = tl.parse_alarms(str(ext.settings.get("alarms") or ""), REJECTED)
BY_NAME = {x["name"].lower(): x for x in TIMERS} | {x["id"]: x for x in TIMERS}

for x in TIMERS:
    ext.device(
        x["id"],
        x["name"],
        [
            {"id": "on", "type": "bool", "access": "rw"},
            {"id": "remaining", "type": "num", "unit": "min", "access": "r"},
            {"id": "minutes", "type": "num", "unit": "min", "access": "rw", "min": 1, "step": 1},
            {"id": "ends", "type": "text", "access": "r"},
        ],
        kind="timer",
        model="Timer",
    )
for x in ALARMS:
    ext.device(
        x["id"],
        x["name"],
        [
            {"id": "on", "type": "bool", "access": "rw"},
            {"id": "time", "type": "text", "access": "rw"},
            {"id": "days", "type": "text", "access": "rw"},
            {"id": "next", "type": "text", "access": "r"},
        ],
        kind="clock",
        model="Alarm",
    )


def load() -> dict[str, Any]:
    try:
        data = json.loads(STATE.read_text("utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        ext.log.warning("state unreadable, timers start fresh: %s", e)
        return {}
    return data if isinstance(data, dict) else {}


saved = load()
timers: dict[str, dict[str, Any]] = {}
for x in TIMERS:
    old = (saved.get("timers") or {}).get(x["id"]) or {}
    same = old.get("base") == x["minutes"]
    timers[x["id"]] = {
        "name": x["name"],
        "base": x["minutes"],
        "minutes": old.get("minutes", x["minutes"]) if same else x["minutes"],
        "ends": old.get("ends"),
    }
alarms: dict[str, dict[str, Any]] = {}
for x in ALARMS:
    old = (saved.get("alarms") or {}).get(x["id"]) or {}
    base = f"{x['time']} {x['days']}"
    same = old.get("base") == base
    alarms[x["id"]] = {
        "name": x["name"],
        "base": base,
        "on": old.get("on", True),
        "time": old.get("time", x["time"]) if same else x["time"],
        "days": old.get("days", x["days"]) if same else x["days"],
    }
st: dict[str, Any] = {
    "tz": ZoneInfo("Europe/Helsinki"),
    "lang": "uk",
    "cal": {},
    "cal_at": 0.0,
    "last": None,
    "pub": {},
}


def save() -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps({"timers": timers, "alarms": alarms, "devices": sorted([*timers, *alarms])}), "utf-8")
    tmp.replace(STATE)


def now() -> datetime:
    return datetime.now(st["tz"])


def is_workday(d: date) -> bool:
    cal, today = st["cal"], now().date()
    if d == today and isinstance(cal.get("workday"), bool):
        return cal["workday"]
    if d == today + timedelta(days=1) and isinstance(cal.get("tomorrow_workday"), bool):
        return cal["tomorrow_workday"]
    return d.weekday() < 5


def needs_calendar() -> bool:
    return any((tl.parse_days(a["days"]) or ("days", set()))[0] != "days" for a in alarms.values())


async def refresh_calendar() -> None:
    if time.time() - st["cal_at"] < CAL_EVERY or not needs_calendar():
        return
    st["cal_at"] = time.time()
    try:
        devs = await ext.call("devices.list")
        cal = next((d for d in devs if d.get("kind") == "calendar" and d.get("available", True)), None)
        st["cal"] = (cal or {}).get("state") or {}
    except Exception as e:
        ext.log.warning("calendar state unavailable: %s", e)


def timer_values(tid: str) -> dict[str, Any]:
    t = timers[tid]
    ends = t.get("ends")
    running = bool(ends and ends > time.time())
    return {
        "on": running,
        "remaining": tl.remaining_min(ends, time.time()) if running else 0,
        "minutes": t["minutes"],
        "ends": datetime.fromtimestamp(ends, st["tz"]).strftime("%H:%M:%S") if running else "",
    }


def alarm_values(aid: str) -> dict[str, Any]:
    a = alarms[aid]
    at = tl.next_alarm(now(), a["time"], a["days"], is_workday) if a["on"] else None
    return {"on": a["on"], "time": a["time"], "days": a["days"], "next": tl.fmt_next(at, now(), st["lang"])}


async def publish(dev: str, values: dict[str, Any], force: bool = False) -> None:
    if force or st["pub"].get(dev) != values:
        st["pub"][dev] = values
        await ext.state(dev, values)
        await ext.changed("timers")


async def start_timer(tid: str, minutes: float | None = None) -> dict[str, Any]:
    t = timers[tid]
    if minutes:
        t["minutes"] = max(min(float(minutes), tl.MAX_MINUTES), 0.05)
    t["ends"] = time.time() + t["minutes"] * 60
    save()
    ext.log.info("timer %s started for %s min", t["name"], t["minutes"])
    await ext.trigger("timer_started", {"timer": t["name"], "minutes": t["minutes"]})
    values = timer_values(tid)
    await publish(tid, values)
    return values


async def cancel_timer(tid: str) -> dict[str, Any]:
    timers[tid]["ends"] = None
    save()
    ext.log.info("timer %s cancelled", timers[tid]["name"])
    values = timer_values(tid)
    await publish(tid, values)
    return values


def make_timer_setter(tid: str) -> Any:
    async def setter(values: dict[str, Any]) -> dict[str, Any]:
        t = timers[tid]
        if "minutes" in values:
            m = values["minutes"]
            if isinstance(m, bool) or not isinstance(m, (int, float)) or not 0 < m <= tl.MAX_MINUTES:
                raise ValueError(f"minutes must be between 1 and {tl.MAX_MINUTES}")
            t["minutes"] = float(m)
            save()
        if values.get("on") is True:
            return await start_timer(tid)
        if values.get("on") is False:
            return await cancel_timer(tid)
        out = timer_values(tid)
        await publish(tid, out)
        return out

    return setter


def make_alarm_setter(aid: str) -> Any:
    async def setter(values: dict[str, Any]) -> dict[str, Any]:
        a = alarms[aid]
        if isinstance(values.get("on"), bool):
            a["on"] = values["on"]
        if "time" in values:
            if tl.parse_time(str(values["time"])) is None:
                raise ValueError("time must be HH:MM")
            a["time"] = str(values["time"]).strip()
        if "days" in values:
            if tl.parse_days(str(values["days"])) is None:
                raise ValueError("days not recognised")
            a["days"] = str(values["days"]).strip()
        save()
        ext.log.info("alarm %s set to %s %s, on %s", a["name"], a["time"], a["days"], a["on"])
        out = alarm_values(aid)
        await publish(aid, out)
        return out

    return setter


for _tid in timers:
    ext.on_set(_tid)(make_timer_setter(_tid))
for _aid in alarms:
    ext.on_set(_aid)(make_alarm_setter(_aid))


@ext.on_start
async def started() -> None:
    for line in REJECTED:
        ext.log.warning("settings line ignored: %s", line)
    try:
        home = await ext.call("home")
        st["tz"] = ZoneInfo(home.get("timezone") or "Europe/Helsinki")
        st["lang"] = home.get("lang") or "uk"
    except Exception as e:
        ext.log.warning("home info unavailable: %s", e)
    for dev in set(saved.get("devices") or []) - set(timers) - set(alarms):
        await ext.available(dev, False)
        ext.log.info("device %s removed from settings, marked offline", dev)
    save()


async def tick() -> None:
    await refresh_calendar()
    t, ts = now(), time.time()
    for tid, x in timers.items():
        if x.get("ends") and x["ends"] <= ts:
            x["ends"] = None
            save()
            ext.log.info("timer %s finished", x["name"])
            await ext.trigger("timer_finished", {"timer": x["name"], "minutes": x["minutes"]})
        await publish(tid, timer_values(tid))
    last = st["last"]
    for aid, a in alarms.items():
        if a["on"] and last is not None and tl.due(last, t, a["time"], a["days"], is_workday):
            ext.log.info("alarm %s at %s", a["name"], a["time"])
            await ext.trigger("alarm", {"alarm": a["name"], "at": a["time"]})
        await publish(aid, alarm_values(aid))
    st["last"] = t


@ext.loop
async def loop() -> None:
    while True:
        try:
            await tick()
        except Exception as e:
            ext.log.error("timers tick failed: %s", e)
        await asyncio.sleep(TICK)


def find(params: dict) -> str:
    key = str(params.get("timer") or "").strip().lower()
    x = BY_NAME.get(key) or BY_NAME.get(tl.slug(key, "t"))
    if x is None:
        raise KeyError(f"timer not found: {params.get('timer')}")
    return x["id"]


@ext.block("start_timer")
async def b_start(params: dict, token: dict, dry: bool) -> dict:
    tid = find(params)
    minutes = float(params["minutes"]) if params.get("minutes") else None
    if not dry:
        await start_timer(tid, minutes)
    m = minutes or timers[tid]["minutes"]
    return {"outs": [[0]], "trace": {"s": "ok", "m": "ext_value", "p": {"value": timers[tid]["name"], "target": m}}}


@ext.block("cancel_timer")
async def b_cancel(params: dict, token: dict, dry: bool) -> dict:
    tid = find(params)
    if not dry:
        await cancel_timer(tid)
    return {"outs": [[0]], "trace": {"s": "ok", "m": "ext_value", "p": {"value": timers[tid]["name"], "target": 0}}}


@ext.block("timer_running")
async def b_running(params: dict, token: dict, dry: bool) -> dict:
    tid = find(params)
    v = timer_values(tid)
    ok = v["on"]
    return {
        "outs": [[0, {"timer": timers[tid]["name"], "remaining": v["remaining"]}] if ok else [1]],
        "trace": {"s": "ok" if ok else "no", "m": "ext_value", "p": {"value": v["remaining"], "target": 0}},
    }


def L(uk: str, ru: str, en: str) -> dict[str, str]:
    return {"uk": uk, "ru": ru, "en": en}


def timer_row(tid: str, x: dict[str, Any]) -> dict[str, Any]:
    v = timer_values(tid)
    hint = L(f"таймер {x['name']}", f"таймер {x['name']}", f"timer {x['name']}")
    if v["on"]:
        return {
            "text": x["name"],
            "values": [
                {"value": v["remaining"], "unit": "min", "digits": 0},
                L(f"до {v['ends']}", f"до {v['ends']}", f"until {v['ends']}"),
            ],
            "action": {"key": f"cancel:{tid}", "label": L("Зупинити", "Остановить", "Stop"), "icon": "x", "hint": hint},
        }
    m = float(x["minutes"])
    return {
        "text": x["name"],
        "values": [{"value": m, "unit": "min", "digits": 0 if m.is_integer() else 1}],
        "action": {"key": f"start:{tid}", "label": L("Запустити", "Запустить", "Start"), "icon": "play", "hint": hint},
    }


def timers_blocks(lang: str) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    if timers:
        items = [timer_row(tid, x) for tid, x in timers.items()]
        blocks.append({"type": "list", "label": L("Таймери", "Таймеры", "Timers"), "items": items})
    if alarms:
        items = []
        for aid, a in alarms.items():
            v = alarm_values(aid)
            nxt = v["next"] or "-"
            off = L("вимкнено", "выключен", "off")
            text = f"{a['name']}, {a['time']} {tl.fmt_days(a['days'], lang)}".strip()
            items.append({"text": text, "value": nxt if a["on"] else off})
        blocks.append({"type": "list", "label": L("Будильники", "Будильники", "Alarms"), "items": items})
    if REJECTED:
        blocks.append(
            {
                "type": "text",
                "text": L(
                    f"Рядки налаштувань не розібрано: {'; '.join(REJECTED)}",
                    f"Строки настроек не разобраны: {'; '.join(REJECTED)}",
                    f"Settings lines not understood: {'; '.join(REJECTED)}",
                ),
            }
        )
    if not blocks:
        blocks.append(
            {
                "type": "text",
                "text": L(
                    "Додайте таймери і будильники в налаштуваннях розширення",
                    "Добавьте таймеры и будильники в настройках расширения",
                    "Add timers and alarms in the extension settings",
                ),
            }
        )
    return blocks


@ext.page("timers")
async def page_timers(params: dict) -> dict:
    action = str(params.get("action") or "")
    if action:
        op, _, tid = action.partition(":")
        if tid in timers and op == "start":
            await start_timer(tid)
        elif tid in timers and op == "cancel":
            await cancel_timer(tid)
    return {"blocks": timers_blocks(str(params.get("lang") or st["lang"])), "updated": now().isoformat()}


if __name__ == "__main__":
    ext.run()
