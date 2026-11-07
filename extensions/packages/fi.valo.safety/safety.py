import asyncio
import json
import time
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import safetylogic as sl
from valo_sdk import Extension

ext = Extension()
STATE = ext.data / "state.json"
POLL = 60
TICK = 10
WIDGET_ROWS = 4
DEV = "safety"
NAME = {"uk": "Безпека дому", "ru": "Безопасность дома", "en": "Home safety"}
CAPS = [
    {"id": "armed", "type": "bool", "access": "rw", "name": "Armed"},
    {"id": "alarm", "type": "bool", "access": "r", "name": "Alarm"},
    {"id": "sensors", "type": "num", "access": "r", "name": "Sensors"},
    {"id": "warnings", "type": "num", "access": "r", "name": "Warnings"},
    {"id": "tested", "type": "text", "access": "r", "name": "Smoke test"},
]
ext.device(DEV, NAME, CAPS, kind="safety", model="Home safety", service=True)


def L(uk: str, ru: str, en: str) -> dict[str, str]:
    return {"uk": uk, "ru": ru, "en": en}


KIND = {
    "leak": L("Протікання", "Протечка", "Leak"),
    "smoke": L("Дим", "Дым", "Smoke"),
    "co": L("Чадний газ", "Угарный газ", "Carbon monoxide"),
    "gas": L("Витік газу", "Утечка газа", "Gas leak"),
}
ICON = {"leak": "drop", "smoke": "flame", "co": "warn", "gas": "flame"}


def load() -> dict[str, Any]:
    try:
        data = json.loads(STATE.read_text("utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        ext.log.warning("state unreadable, safety starts fresh: %s", e)
        return {}
    return data if isinstance(data, dict) else {}


saved = load()
incidents: list[dict[str, Any]] = sl.restore(saved.get("incidents"))
st: dict[str, Any] = {
    "armed": saved.get("armed") is not False,
    "tested": saved.get("tested") if isinstance(saved.get("tested"), str) else None,
    "reminded": saved.get("reminded") if isinstance(saved.get("reminded"), str) else None,
    "tz": ZoneInfo("Europe/Helsinki"),
    "names": {},
    "rooms": {},
    "polled": 0.0,
    "pub": None,
}
active_saved = saved.get("active") if isinstance(saved.get("active"), dict) else {}
remembered: dict[str, list[str]] = {
    k: [x for x in v if x in sl.KINDS] for k, v in active_saved.items() if isinstance(v, list)
}
sens: dict[str, dict[str, Any]] = {}
lock = asyncio.Lock()
EXCLUDE = set(sl.parse_ids(ext.settings.get("exclude")))
SHUTOFF = sl.parse_ids(ext.settings.get("shutoff"))


def test_every() -> float:
    v = sl.num(ext.settings.get("test_days"))
    return v if v and v > 0 else 30.0


def save() -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    data = {
        "armed": st["armed"],
        "tested": st["tested"],
        "reminded": st["reminded"],
        "incidents": incidents,
        "active": {d: sl.active(s) for d, s in sens.items() if sl.active(s)},
    }
    tmp.write_text(json.dumps(data), "utf-8")
    tmp.replace(STATE)


def now() -> datetime:
    return datetime.now(st["tz"])


def lang_of(x: dict[str, str]) -> str:
    return x.get(ext.lang) or x["en"]


def room_name(s: dict[str, Any]) -> str:
    return str(st["rooms"].get(s.get("room") or "", ""))


def smoke_sensors() -> list[dict[str, Any]]:
    return [s for s in sens.values() if "smoke" in s["kinds"]]


def alarms() -> list[tuple[str, str, str]]:
    """Текущие тревоги: датчик в тревоге или неподтвержденный инцидент, по одной на устройство и вид."""
    out: dict[tuple[str, str], str] = {}
    t = time.time()
    for s in sens.values():
        for k in sl.active(s):
            if not sl.is_test(s, k, t):
                out[(s["id"], k)] = s["name"]
    for i in incidents:
        if not i.get("acked"):
            out.setdefault((str(i.get("device")), str(i["kind"])), str(i.get("name") or i.get("device")))
    return [(d, k, n) for (d, k), n in out.items()]


def values() -> dict[str, Any]:
    c = sl.counts(list(sens.values()))
    return {
        "armed": st["armed"],
        "alarm": sl.alarm_on(incidents, list(sens.values()), time.time()),
        "sensors": c["sensors"],
        "warnings": c["warnings"],
        "tested": fmt_day(st["tested"]),
    }


def fmt_day(iso: Any) -> str:
    return f"{iso[8:10]}.{iso[5:7]}.{iso[:4]}" if isinstance(iso, str) and len(iso) == 10 else ""


async def publish(force: bool = False) -> None:
    v = values()
    if force or v != st["pub"]:
        st["pub"] = v
        await ext.state(DEV, v)
        await ext.changed("safety", "status")


async def notify(key: str, level: str, text: str) -> None:
    try:
        await ext.call("notify", {"key": key, "level": level, "text": text})
    except Exception as e:
        ext.log.error("notification %s not sent: %s", key, e)


async def shutoff() -> list[str]:
    done: list[str] = []
    for did in SHUTOFF:
        name = st["names"].get(did, did)
        try:
            await ext.call("devices.command", {"id": did, "values": {"on": False}})
            done.append(name)
            ext.log.warning("leak shutoff: switched off %s (%s)", name, did)
        except Exception as e:
            ext.log.error("leak shutoff: %s (%s) not switched off: %s", name, did, e)
    return done


async def raised(s: dict[str, Any], kind: str) -> None:
    t = time.time()
    if sl.is_test(s, kind, t):
        sl.open_incident(incidents, s, kind, t, test=True)
        st["tested"] = now().date().isoformat()
        ext.log.info("smoke test on %s (%s), test date recorded", s["name"], s["id"])
        return
    inc = sl.open_incident(incidents, s, kind, t)
    room = room_name(s)
    where = f"{s['name']}, {room}" if room else s["name"]
    ext.log.warning("alarm %s on %s (%s), armed %s", kind, s["name"], s["id"], st["armed"])
    if st["armed"] and kind == "leak" and SHUTOFF:
        inc["shutoff"] = await shutoff()
    off = ", ".join(inc["shutoff"])
    extra = {"uk": f". Вимкнено: {off}", "ru": f". Отключено: {off}", "en": f". Switched off: {off}"}
    text = f"{lang_of(KIND[kind])}: {where}" + (lang_of(extra) if off else "")
    await notify(f"alarm:{inc['id']}:{s['id']}", "crit", text)
    await ext.trigger(
        "alarm",
        {"kind": kind, "device": s["id"], "name": s["name"], "room": room, "what": lang_of(KIND[kind]), "shutoff": off},
    )


async def ingest(s: dict[str, Any], vals: Any) -> bool:
    up, down = sl.apply(s, vals, time.time())
    for k in down:
        sl.close_incidents(incidents, s["id"], k, time.time())
        ext.log.info("%s on %s (%s) ended", k, s["name"], s["id"])
    for k in up:
        await raised(s, k)
    return bool(up or down)


async def poll() -> None:
    devs = await ext.call("devices.list")
    if not isinstance(devs, list):
        raise ValueError("devices.list returned no list")
    try:
        rooms = await ext.call("rooms")
        st["rooms"] = {r["id"]: r["name"] for r in rooms if isinstance(r, dict) and "id" in r}
    except Exception as e:
        ext.log.warning("rooms unavailable: %s", e)
    st["names"] = {d["id"]: str(d.get("name") or d["id"]) for d in devs if isinstance(d, dict) and "id" in d}
    found = sl.sensors(devs, ext.id, EXCLUDE)
    changed = False
    async with lock:
        seen = set()
        for d in found:
            old = sens.get(d["id"])
            if old is None and d["id"] in remembered:
                old = {"state": {k: True for k in remembered.pop(d["id"])}}
            s = sl.sensor(d, old)
            if s is None:
                continue
            if d["id"] not in sens:
                ext.log.info("watching %s (%s): %s", s["name"], s["id"], ", ".join(s["kinds"]))
            sens[d["id"]] = s
            seen.add(d["id"])
            changed = await ingest(s, d.get("state")) or changed
        for gone in set(sens) - seen:
            ext.log.info("sensor %s no longer present", gone)
            sens.pop(gone)
        if changed:
            save()
    st["polled"] = time.time()


async def reminder() -> None:
    if not smoke_sensors():
        return
    today = now().date()
    if not sl.remind(st["tested"], st["reminded"], today, test_every()):
        return
    st["reminded"] = today.isoformat()
    save()
    last = fmt_day(st["tested"])
    text = {
        "uk": "Час перевірити датчики диму кнопкою тесту" + (f", остання перевірка {last}" if last else ""),
        "ru": "Пора проверить датчики дыма кнопкой теста" + (f", последняя проверка {last}" if last else ""),
        "en": "Time to test the smoke detectors with the test button" + (f", last test {last}" if last else ""),
    }
    ext.log.info("smoke test reminder sent")
    await notify(f"smoke_test:{today.isoformat()}", "info", lang_of(text))


@ext.on_start
async def start() -> None:
    try:
        home = await ext.call("home")
        st["tz"] = ZoneInfo(home.get("timezone") or "Europe/Helsinki")
    except Exception as e:
        ext.log.warning("home info unavailable: %s", e)
    for did in SHUTOFF:
        ext.log.info("leak shutoff device %s", did)
    try:
        await poll()
    except Exception as e:
        ext.log.error("first device poll failed: %s", e)
    ext.log.info("watching %s sensors, armed %s", len(sens), st["armed"])
    await publish(force=True)


@ext.loop
async def loop() -> None:
    while True:
        try:
            if time.time() - st["polled"] >= POLL:
                await poll()
            await reminder()
            await publish()
        except Exception as e:
            ext.log.error("safety tick failed: %s", e)
        await asyncio.sleep(TICK)


@ext.subscribe("hub/v1/core/state/+")
async def on_state(topic: str, payload: Any) -> None:
    dev = topic.rsplit("/", 1)[-1]
    if not isinstance(payload, dict):
        return
    try:
        s = sens.get(dev)
        if s is None:
            if dev not in EXCLUDE and any(payload.get(k) is True for k in sl.KINDS) and dev not in st["names"]:
                ext.log.info("alarm from unknown device %s, refreshing the device list", dev)
                await poll()
                await publish()
            return
        async with lock:
            if await ingest(s, payload):
                save()
        await publish()
    except Exception as e:
        ext.log.error("state of %s not processed: %s", dev, e)


async def set_armed(on: bool) -> None:
    if st["armed"] != on:
        st["armed"] = on
        save()
        ext.log.info("armed %s", on)
    await publish()


async def do_ack() -> int:
    n = sl.ack(incidents)
    save()
    ext.log.info("alarm acknowledged, incidents %s", n)
    await publish()
    return n


async def tested_today() -> None:
    st["tested"] = now().date().isoformat()
    save()
    ext.log.info("smoke test marked done")
    await publish()


@ext.on_set(DEV)
async def on_set(vals: dict[str, Any]) -> dict[str, Any]:
    if "armed" in vals:
        if not isinstance(vals["armed"], bool):
            raise ValueError("armed must be true or false")
        await set_armed(vals["armed"])
    return values()


def done(label: str, value: Any) -> dict[str, Any]:
    return {"outs": [[0]], "trace": {"s": "ok", "m": "ext_value", "p": {"value": label, "target": value}}}


@ext.block("armed")
async def b_armed(params: dict, token: dict, dry: bool) -> dict:
    ok = bool(st["armed"])
    return {"outs": [[0] if ok else [1]], "trace": {"s": "ok" if ok else "no", "m": "ext_value", "p": {"value": ok}}}


@ext.block("arm")
async def b_arm(params: dict, token: dict, dry: bool) -> dict:
    if not dry:
        await set_armed(True)
    return done("armed", True)


@ext.block("disarm")
async def b_disarm(params: dict, token: dict, dry: bool) -> dict:
    if not dry:
        await set_armed(False)
    return done("armed", False)


@ext.block("ack")
async def b_ack(params: dict, token: dict, dry: bool) -> dict:
    n = 0 if dry else await do_ack()
    return done("ack", n)


def state_text(s: dict[str, Any]) -> dict[str, str]:
    act = sl.active(s)
    if act:
        return {x: ", ".join(KIND[k][x] for k in act) for x in ("uk", "ru", "en")}
    if not s["available"]:
        return L("Немає зв'язку", "Нет связи", "Offline")
    return L("Норма", "Норма", "Normal")


def sensor_row(s: dict[str, Any], full: bool) -> dict[str, Any]:
    parts: list[Any] = [state_text(s)]
    if s.get("bat") is not None and (full or sl.low_battery(s)):
        parts.append({"value": s["bat"], "unit": "%", "digits": 0})
    if full:
        seen = sl.seen_text(s.get("seen"), st["tz"], now())
        if seen:
            parts.append({"text": seen})
    room = room_name(s)
    return {"text": f"{s['name']}, {room}" if full and room else s["name"], "values": parts}


def hero() -> dict[str, Any]:
    al = alarms()
    c = sl.counts(list(sens.values()))
    sub: list[Any] = [
        {"label": L("Датчики", "Датчики", "Sensors"), "value": c["sensors"], "digits": 0},
        L("охорону ввімкнено", "охрана включена", "armed")
        if st["armed"]
        else L("охорону вимкнено", "охрана выключена", "disarmed"),
    ]
    items: list[dict[str, Any]] = [{"icon": ICON[k], "label": KIND[k], "value": c[k]} for k in sl.KINDS if c[k]]
    low = sum(1 for s in sens.values() if sl.low_battery(s))
    off = sum(1 for s in sens.values() if not s["available"])
    if low:
        items.append({"icon": "battery", "label": L("Низький заряд", "Низкий заряд", "Low battery"), "value": low})
    if off:
        items.append({"icon": "wifi", "label": L("Немає зв'язку", "Нет связи", "Offline"), "value": off})
    items = [it | {"digits": 0} for it in items]
    if al:
        _, k, n = al[0]
        more = len(al) - 1
        text = {x: f"{KIND[k][x]}: {n}" for x in ("uk", "ru", "en")}
        if more:
            text = {
                "uk": f"{text['uk']} і ще {more}",
                "ru": f"{text['ru']} и еще {more}",
                "en": f"{text['en']} and {more} more",
            }
        return {"type": "hero", "icon": "warn", "tone": "crit", "value": len(al), "digits": 0, "text": text, "sub": sub}
    if not sens:
        text = L("Датчиків безпеки не знайдено", "Датчиков безопасности не найдено", "No safety sensors found")
        return {"type": "hero", "icon": "shield", "tone": "", "text": text, "sub": sub}
    warn = low or off or (smoke_sensors() and sl.test_due(st["tested"], now().date(), test_every()))
    text = L("Все спокійно", "Все спокойно", "All calm")
    tone = "warn" if warn else "ok"
    return {"type": "hero", "icon": "shield", "tone": tone, "text": text, "sub": sub} | (
        {"items": items} if items else {}
    )


def incident_row(i: dict[str, Any]) -> dict[str, Any]:
    at = datetime.fromtimestamp(float(i.get("ts") or 0), st["tz"]).strftime("%d.%m %H:%M")
    if i.get("test"):
        status = L("перевірка", "проверка", "test")
    elif i.get("end") is None:
        status = L("триває", "продолжается", "ongoing")
    elif not i.get("acked"):
        status = L("не підтверджено", "не подтверждено", "not acknowledged")
    else:
        status = L("завершено", "завершено", "ended")
    parts: list[Any] = [{"text": at}, status]
    if i.get("shutoff"):
        off = ", ".join(i["shutoff"])
        parts.append(L(f"вимкнено {off}", f"отключено {off}", f"switched off {off}"))
    kind = KIND.get(str(i.get("kind")), L("Тривога", "Тревога", "Alarm"))
    name = str(i.get("name") or i.get("device") or "")
    return {"text": {x: f"{kind[x]}: {name}" for x in ("uk", "ru", "en")}, "values": parts}


def test_row() -> dict[str, Any]:
    last = fmt_day(st["tested"])
    due = sl.test_due(st["tested"], now().date(), test_every())
    if not last:
        value: Any = L("ще не перевіряли", "еще не проверяли", "never tested")
    elif due:
        value = L(f"пора, була {last}", f"пора, была {last}", f"due, last {last}")
    else:
        value = {"text": last}
    return {
        "text": L("Перевірка датчиків диму", "Проверка датчиков дыма", "Smoke detector test"),
        "values": [value],
        "action": {
            "key": "tested",
            "label": L("Перевірено сьогодні", "Проверено сегодня", "Tested today"),
            "icon": "check",
        },
    }


def page_blocks() -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = [hero()]
    ordered = sorted(sens.values(), key=lambda s: (sl.rank(s), s["name"]))
    if ordered:
        blocks.append(
            {
                "type": "list",
                "label": L("Датчики", "Датчики", "Sensors"),
                "items": [sensor_row(s, True) for s in ordered],
            }
        )
    attention: list[dict[str, Any]] = []
    for kind, s in sl.warnings(ordered):
        if kind == "offline":
            attention.append({"text": s["name"], "values": [L("немає зв'язку", "нет связи", "offline")]})
        else:
            attention.append(
                {
                    "text": s["name"],
                    "values": [
                        L("замініть батарею", "замените батарею", "replace the battery"),
                        {"value": s["bat"], "unit": "%", "digits": 0},
                    ],
                }
            )
    if smoke_sensors():
        attention.append(test_row())
    if attention:
        blocks.append({"type": "list", "label": L("Нагадування", "Напоминания", "Reminders"), "items": attention})
    if incidents:
        blocks.append(
            {
                "type": "list",
                "label": L("Події", "События", "Incidents"),
                "items": [incident_row(i) for i in reversed(incidents[-15:])],
            }
        )
    acts: list[dict[str, Any]] = []
    if any(not i.get("acked") for i in incidents):
        label = L("Скинути тривогу", "Сбросить тревогу", "Clear alarm")
        acts.append({"key": "ack", "label": label, "icon": "check", "primary": True})
    if st["armed"]:
        acts.append({"key": "disarm", "label": L("Зняти з охорони", "Снять с охраны", "Disarm"), "icon": "lock"})
    else:
        acts.append({"key": "arm", "label": L("Поставити на охорону", "Поставить на охрану", "Arm"), "icon": "shield"})
    if incidents:
        acts.append({"key": "clear", "label": L("Очистити журнал", "Очистить журнал", "Clear log"), "icon": "trash"})
    blocks.append({"type": "actions", "items": acts})
    if not SHUTOFF:
        blocks.append(
            {
                "type": "text",
                "text": L(
                    "Щоб при протіканні вимикати насос, бойлер або кран, вкажіть їх у налаштуваннях розширення",
                    "Чтобы при протечке отключать насос, бойлер или кран, укажите их в настройках расширения",
                    "To switch off a pump, boiler or valve on a leak, list them in the extension settings",
                ),
            }
        )
    return blocks


async def act(action: str) -> None:
    if action == "arm":
        await set_armed(True)
    elif action == "disarm":
        await set_armed(False)
    elif action == "ack":
        await do_ack()
    elif action == "tested":
        await tested_today()
    elif action == "clear":
        async with lock:
            keep = [i for i in incidents if not i.get("acked") or i.get("end") is None]
            incidents[:] = keep
            save()
        ext.log.info("incident log cleared, kept %s open", len(keep))
        await publish(force=True)


@ext.page("safety")
async def page_safety(params: dict) -> dict:
    action = str(params.get("action") or "")
    if action:
        await act(action)
    return {"blocks": page_blocks(), "updated": now().isoformat()}


@ext.page("status")
async def page_status(params: dict) -> dict:
    action = str(params.get("action") or "")
    if action:
        await act(action)
    ordered = sorted(sens.values(), key=lambda s: (sl.rank(s), s["name"]))
    blocks: list[dict[str, Any]] = [hero()]
    if ordered:
        shown = WIDGET_ROWS if len(ordered) <= WIDGET_ROWS else WIDGET_ROWS - 1
        rows = [sensor_row(s, False) for s in ordered[:shown]]
        rest = len(ordered) - shown
        if rest > 0:
            rows.append({"text": L(f"Ще {rest}", f"Еще {rest}", f"{rest} more")})
        blocks.append({"type": "list", "label": L("Датчики", "Датчики", "Sensors"), "items": rows})
    return {"blocks": blocks}


if __name__ == "__main__":
    ext.run()
