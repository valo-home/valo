import asyncio
import json
import time
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import plugguardlogic as pl
from valo_sdk import Extension

ext = Extension()
LEDGER = ext.data / "today.json"
TICK = 1
POLL = 60
SAVE_EVERY = 60
NOTIFY_EVERY = 600
PUB_EVERY = 30
DEV = "plugs"
NAME = {"uk": "Контроль розеток", "ru": "Контроль розеток", "en": "Plug guard"}
CAPS = [
    {"id": "w", "type": "num", "unit": "W", "access": "r"},
    {"id": "today_kwh", "type": "num", "unit": "kWh", "access": "r", "name": "today_kwh"},
    {"id": "peak", "type": "num", "unit": "W", "access": "r", "name": "Peak today"},
    {"id": "trips", "type": "num", "access": "r", "name": "Overloads today"},
    {"id": "plugs", "type": "num", "access": "r", "name": "Plugs"},
]
ext.device(DEV, NAME, CAPS, kind="plugguard", model="Plug guard")


def setting(key: str, default: float) -> float:
    v = pl.num(ext.settings.get(key))
    return v if v is not None and v > 0 else default


LIMIT = setting("limit_w", 2500)
DELAY = setting("delay_s", 10)
LOW_W = setting("standby_w", 3)
LOW_MIN = setting("standby_min", 30)
STANDBY = set(pl.parse_ids(ext.settings.get("standby")))
KEEP_ON = set(pl.parse_ids(ext.settings.get("keep_on")))


def L(uk: str, ru: str, en: str) -> dict[str, str]:
    return {"uk": uk, "ru": ru, "en": en}


def load() -> dict[str, Any]:
    try:
        data = json.loads(LEDGER.read_text("utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        ext.log.warning("daily totals unreadable, starting fresh: %s", e)
        return {}
    if not pl.valid(data):
        ext.log.warning("daily totals have unexpected structure, starting fresh")
        return {}
    return data


ledger: dict[str, Any] = load()
watches: dict[str, dict[str, Any]] = {}
notified: dict[str, float] = {}
st: dict[str, Any] = {
    "tz": ZoneInfo("Europe/Helsinki"),
    "polled": 0.0,
    "tick": None,
    "saved": 0.0,
    "pub": None,
    "pub_at": 0.0,
    "changed_at": 0.0,
}


def now() -> datetime:
    return datetime.now(st["tz"])


def save() -> None:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    tmp = LEDGER.with_suffix(".tmp")
    tmp.write_text(json.dumps(ledger), "utf-8")
    tmp.replace(LEDGER)
    st["saved"] = time.time()


def total_w() -> float:
    return round(sum(w["w"] or 0.0 for w in watches.values() if w["available"] and w["on"] is not False), 1)


def values() -> dict[str, Any]:
    rows = ledger.get("plugs", {})
    return {
        "w": round(total_w()),
        "today_kwh": round(pl.total_kwh(ledger), 3),
        "peak": round(max((r.get("peak", 0.0) for r in rows.values()), default=0.0)),
        "trips": sum(int(r.get("trips", 0)) for r in rows.values()),
        "plugs": len(watches),
    }


async def publish(force: bool = False) -> None:
    v = values()
    old = st["pub"] or {}
    t = time.time()
    jump = abs(v["w"] - old.get("w", 0)) >= max(20.0, 0.1 * old.get("w", 0))
    if force or (v != old and (jump or t - st["pub_at"] >= PUB_EVERY or v["trips"] != old.get("trips"))):
        st["pub"], st["pub_at"] = v, t
        await ext.state(DEV, v)
        await ext.changed("plugs", "now")


async def poll() -> None:
    devs = await ext.call("devices.list")
    if not isinstance(devs, list):
        raise ValueError("devices.list returned no list")
    found = {d["id"]: d for d in pl.plugs(devs, ext.id)}
    for did, d in found.items():
        if did not in watches:
            ext.log.info("watching plug %s (%s)", d.get("name"), did)
        watches[did] = pl.watch(d, watches.get(did))
    for gone in set(watches) - set(found):
        ext.log.info("plug %s no longer present", gone)
        watches.pop(gone)
    st["polled"] = time.time()


async def switch(w: dict[str, Any], on: bool) -> bool:
    try:
        await ext.call("devices.command", {"id": w["id"], "values": {"on": on}})
        return True
    except Exception as e:
        ext.log.error("command on=%s for %s (%s) failed: %s", on, w["name"], w["id"], e)
        return False


async def journal(text: str, level: str) -> None:
    try:
        await ext.call("event", {"text": text, "level": level})
    except Exception as e:
        ext.log.warning("journal entry not written: %s", e)


async def on_overload(w: dict[str, Any], t: float) -> None:
    p = w["w"]
    pl.tripped(w, t)
    ok = await switch(w, False)
    pl.row(ledger, w["id"])["trips"] += 1
    save()
    ext.log.warning(
        "overload: %s (%s) drew %.0f W above %.0f W for %.0f s, switched off %s",
        w["name"],
        w["id"],
        p,
        LIMIT,
        DELAY,
        ok,
    )
    if t - notified.get(w["id"], 0.0) < NOTIFY_EVERY:
        await publish(force=True)
        return
    notified[w["id"]] = t
    lang = ext.lang if ext.lang in ("uk", "ru", "en") else "en"
    text = {
        "uk": f"Перевантаження: {w['name']} {p:.0f} Вт понад {LIMIT:.0f} Вт, розетку вимкнено",
        "ru": f"Перегрузка: {w['name']} {p:.0f} Вт больше {LIMIT:.0f} Вт, розетка выключена",
        "en": f"Overload: {w['name']} {p:.0f} W above {LIMIT:.0f} W, plug switched off",
    }[lang]
    if not ok:
        text += {"uk": ". Вимкнути не вдалося", "ru": ". Выключить не удалось", "en": ". Switching off failed"}[lang]
    try:
        await ext.call("notify", {"key": f"overload:{w['id']}:{int(t)}", "level": "warn", "text": text})
    except Exception as e:
        ext.log.error("overload notification not sent: %s", e)
    await ext.trigger("overload", {"device": w["id"], "name": w["name"], "w": round(p), "limit": round(LIMIT)})
    await publish(force=True)


async def on_standby(w: dict[str, Any], t: float) -> None:
    p = w["w"]
    pl.tripped(w, t)
    ok = await switch(w, False)
    ext.log.info("standby: %s (%s) below %.1f W for %.0f min, switched off %s", w["name"], w["id"], LOW_W, LOW_MIN, ok)
    if ok:
        lang = ext.lang if ext.lang in ("uk", "ru", "en") else "en"
        text = {
            "uk": f"{w['name']} вимкнено після {LOW_MIN:.0f} хв простою",
            "ru": f"{w['name']} выключена после {LOW_MIN:.0f} мин простоя",
            "en": f"{w['name']} switched off after {LOW_MIN:.0f} min in standby",
        }[lang]
        await journal(text, "info")
        await ext.trigger(
            "standby_off", {"device": w["id"], "name": w["name"], "w": round(p, 1), "minutes": round(LOW_MIN)}
        )


async def tick() -> None:
    t = time.time()
    local = now()
    if pl.roll(ledger, local.date()):
        ext.log.info("new day %s", ledger["day"])
        save()
    dt = t - st["tick"] if st["tick"] is not None else 0.0
    st["tick"] = t
    for w in list(watches.values()):
        pl.advance(ledger, w, dt, local.hour)
        if w["id"] not in KEEP_ON and pl.overload(w, t, LIMIT, DELAY):
            await on_overload(w, t)
        elif w["id"] in STANDBY and pl.standby(w, t, LOW_W, LOW_MIN):
            await on_standby(w, t)
    if t - st["saved"] >= SAVE_EVERY:
        save()
    await publish()


@ext.on_start
async def start() -> None:
    try:
        home = await ext.call("home")
        st["tz"] = ZoneInfo(home.get("timezone") or "Europe/Helsinki")
    except Exception as e:
        ext.log.warning("home info unavailable: %s", e)
    pl.roll(ledger, now().date())
    try:
        await poll()
    except Exception as e:
        ext.log.error("first device poll failed: %s", e)
    ext.log.info(
        "watching %s plugs, limit %.0f W for %.0f s, standby %s below %.1f W for %.0f min",
        len(watches),
        LIMIT,
        DELAY,
        ", ".join(sorted(STANDBY)) or "off",
        LOW_W,
        LOW_MIN,
    )
    for did in STANDBY - set(watches):
        ext.log.warning("standby device %s is not a switchable plug with power metering", did)
    await publish(force=True)


@ext.loop
async def loop() -> None:
    while True:
        try:
            if time.time() - st["polled"] >= POLL:
                await poll()
            await tick()
        except Exception as e:
            ext.log.error("plug guard tick failed: %s", e)
        await asyncio.sleep(TICK)


@ext.subscribe("hub/v1/core/state/+")
async def on_state(topic: str, payload: Any) -> None:
    w = watches.get(topic.rsplit("/", 1)[-1])
    if w is None or not isinstance(payload, dict):
        return
    try:
        pl.update(w, payload)
    except Exception as e:
        ext.log.error("state of %s not processed: %s", w["id"], e)


@ext.block("power_above")
async def b_power_above(params: dict, token: dict, dry: bool) -> dict:
    did = str(params.get("device") or token.get("d") or "")
    limit = pl.num(params.get("value"))
    limit = limit if limit is not None else 0.0
    w = watches.get(did)
    p, name = (w["w"], w["name"]) if w else (None, did)
    if w is None and did:
        try:
            d = await ext.call("devices.get", {"id": did})
            p, name = pl.num((d.get("state") or {}).get("w")), str(d.get("name") or did)
        except Exception as e:
            ext.log.warning("power of %s unavailable: %s", did, e)
    ok = p is not None and p > limit
    return {
        "outs": [[0, {"power": round(p or 0), "plug": name}] if ok else [1]],
        "trace": {"s": "ok" if ok else "no", "m": "ext_value", "p": {"value": p, "target": limit}},
    }


def status(w: dict[str, Any]) -> dict[str, str]:
    if not w["available"]:
        return L("немає зв'язку", "нет связи", "offline")
    return L("увімкнено", "включена", "on") if w["on"] else L("вимкнено", "выключена", "off")


def dec(x: float) -> dict[str, str]:
    s = f"{x:.1f}"
    return {"uk": s.replace(".", ","), "ru": s.replace(".", ","), "en": s}


def plug_row(w: dict[str, Any], full: bool) -> dict[str, Any]:
    r = ledger.get("plugs", {}).get(w["id"], {})
    parts: list[Any] = [status(w)] if not w["on"] or not w["available"] else []
    if w["w"] is not None and w["available"]:
        parts.append({"value": w["w"], "unit": "W", "digits": 0})
    parts.append({"value": r.get("kwh", 0.0), "unit": "kWh", "digits": 2})
    if full:
        peak = round(r.get("peak", 0.0))
        hours = dec(r.get("on_s", 0.0) / 3600)
        parts.append(L(f"пік {peak} Вт", f"пик {peak} Вт", f"peak {peak} W"))
        parts.append(
            {"uk": f"увімкнена {hours['uk']} год", "ru": f"включена {hours['ru']} ч", "en": f"on {hours['en']} h"}
        )
    row: dict[str, Any] = {"text": w["name"], "values": parts}
    if full and w["available"] and w["on"] is not None:
        hint = L(f"розетка {w['name']}", f"розетка {w['name']}", f"plug {w['name']}")
        if w["on"]:
            row["action"] = {"key": f"off:{w['id']}", "label": L("Вимкнути", "Выключить", "Turn off"), "icon": "power"}
        else:
            row["action"] = {"key": f"on:{w['id']}", "label": L("Увімкнути", "Включить", "Turn on"), "icon": "power"}
        row["action"]["hint"] = hint
    return row


def hero(full: bool) -> dict[str, Any]:
    v = values()
    on = sum(1 for w in watches.values() if w["on"] and w["available"])
    off = sum(1 for w in watches.values() if not w["available"])
    sub: list[Any] = [{"label": L("Сьогодні", "Сегодня", "Today"), "value": v["today_kwh"], "unit": "kWh", "digits": 2}]
    y = pl.yesterday_kwh(ledger, now().date())
    if full and y is not None:
        sub.append({"label": L("вчора", "вчера", "yesterday"), "value": y, "unit": "kWh", "digits": 2})
    items: list[dict[str, Any]] = [
        {"icon": "plug", "label": L("Увімкнено", "Включено", "On"), "value": on},
        {"icon": "bolt", "label": L("Пік сьогодні", "Пик сегодня", "Peak today"), "value": v["peak"], "unit": "W"},
    ]
    if v["trips"]:
        items.append({"icon": "warn", "label": L("Перевантаження", "Перегрузки", "Overloads"), "value": v["trips"]})
    if off:
        items.append({"icon": "wifi", "label": L("Немає зв'язку", "Нет связи", "Offline"), "value": off})
    items = [it | {"digits": 0} for it in items]
    near = any((w["w"] or 0) > 0.8 * LIMIT for w in watches.values() if w["available"] and w["on"])
    tone = "crit" if any(w["over_since"] for w in watches.values()) else "warn" if near or v["trips"] else "amber"
    text = L(
        f"Розеток {len(watches)}, увімкнено {on}",
        f"Розеток {len(watches)}, включено {on}",
        f"{len(watches)} plugs, {on} on",
    )
    if not watches:
        text = L("Розеток з виміром потужності не знайдено", "Розеток с измерением мощности не найдено", "No plugs")
    return {
        "type": "hero",
        "icon": "plug",
        "tone": tone,
        "value": v["w"],
        "unit": "W",
        "digits": 0,
        "text": text,
        "sub": sub,
        "items": items,
    }


def hours_bars() -> dict[str, Any]:
    h = now().hour
    vals = [round(x, 3) for x in ledger.get("hours", [0.0] * 24)[: h + 1]]
    return {
        "type": "bars",
        "label": L(
            "Споживання розеток по годинах, кВт·год", "Потребление розеток по часам, кВт·ч", "Plugs by hour, kWh"
        ),
        "values": vals,
        "labels": [f"{i:02d}:00" for i in range(len(vals))],
        "now": len(vals) - 1,
        "unit": "kWh",
        "digits": 3,
        "series": [
            {"label": L("За годину", "За час", "Per hour"), "color": "amber"},
            {"label": L("Поточна година", "Текущий час", "Current hour"), "color": "frost"},
        ],
        "kinds": [0] * (len(vals) - 1) + [1],
    }


def rules_text() -> dict[str, str]:
    lim, dl = f"{LIMIT:.0f}", f"{DELAY:.0f}"
    text = L(
        f"Розетка вимикається, якщо потужність вище {lim} Вт довше {dl} с",
        f"Розетка выключается, если мощность выше {lim} Вт дольше {dl} с",
        f"A plug is switched off when power stays above {lim} W for {dl} s",
    )
    if STANDBY:
        names = ", ".join(watches[d]["name"] if d in watches else d for d in sorted(STANDBY))
        low, mins = dec(LOW_W), f"{LOW_MIN:.0f}"
        text = {
            "uk": f"{text['uk']}. {names} вимикаються при споживанні нижче {low['uk']} Вт довше {mins} хв",
            "ru": f"{text['ru']}. {names} выключаются при потреблении ниже {low['ru']} Вт дольше {mins} мин",
            "en": f"{text['en']}. {names} are switched off below {low['en']} W for {mins} min",
        }
    return text


async def act(action: str) -> None:
    op, _, did = action.partition(":")
    w = watches.get(did)
    if w is None or op not in ("on", "off"):
        raise ValueError(f"unknown action {action}")
    ext.log.info("page command %s for %s (%s)", op, w["name"], did)
    if await switch(w, op == "on"):
        w["on"] = op == "on"


def ordered() -> list[dict[str, Any]]:
    return sorted(watches.values(), key=lambda w: (-(w["w"] or 0) if w["available"] else 1, w["name"]))


@ext.page("plugs")
async def page_plugs(params: dict) -> dict:
    action = str(params.get("action") or "")
    if action:
        await act(action)
    blocks: list[dict[str, Any]] = [hero(True), hours_bars()]
    if watches:
        blocks.append(
            {
                "type": "list",
                "label": L("Розетки сьогодні", "Розетки сегодня", "Plugs today"),
                "items": [plug_row(w, True) for w in ordered()],
            }
        )
    blocks.append({"type": "text", "text": rules_text()})
    return {"blocks": blocks, "updated": now().isoformat()}


@ext.page("now")
async def page_now(params: dict) -> dict:
    blocks: list[dict[str, Any]] = [hero(False)]
    top = ordered()[:3]
    if top:
        blocks.append(
            {
                "type": "list",
                "label": L("Найбільше зараз", "Больше всего сейчас", "Top now"),
                "items": [plug_row(w, False) for w in top],
            }
        )
    return {"blocks": blocks}


if __name__ == "__main__":
    ext.run()
