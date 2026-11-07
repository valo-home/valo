import asyncio
import json
import time
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import energylogic as el
from valo_sdk import Extension

ext = Extension()
LEDGER = ext.data / "ledger.json"
POLL = 60
CAPS = [
    {"id": "today_kwh", "type": "num", "unit": "kWh", "access": "r", "name": "today_kwh"},
    {"id": "today_cost", "type": "num", "access": "r", "name": "today_cost"},
    {"id": "month_kwh", "type": "num", "unit": "kWh", "access": "r", "name": "month_kwh"},
    {"id": "month_cost", "type": "num", "access": "r", "name": "month_cost"},
    {"id": "year_kwh", "type": "num", "unit": "kWh", "access": "r", "name": "year_kwh"},
    {"id": "year_cost", "type": "num", "access": "r", "name": "year_cost"},
    {"id": "w", "type": "num", "unit": "W", "access": "r"},
    {"id": "price", "type": "num", "access": "r", "name": "price"},
]
NAME = {
    "uk": "Облік енергії",
    "ru": "Учет энергии",
    "en": "Energy usage",
    "de": "Energieverbrauch",
    "es": "Consumo de energía",
    "fr": "Consommation d'énergie",
    "ja": "エネルギー使用量",
}
ext.device("usage", NAME, CAPS, kind="meter")
state: dict[str, Any] = {
    "tz": ZoneInfo("Europe/Helsinki"),
    "currency": "EUR",
    "names": {},
    "w": 0.0,
    "price": 0.0,
    "auto_main": None,
}


def load() -> dict[str, Any]:
    empty: dict[str, Any] = {"meters": {}, "days": {}, "closed": None}
    try:
        data = json.loads(LEDGER.read_text("utf-8"))
    except FileNotFoundError:
        return empty
    except (OSError, ValueError) as e:
        bad = LEDGER.with_suffix(f".bad-{int(time.time())}")
        LEDGER.replace(bad)
        ext.log.error("ledger unreadable (%s), moved to %s, starting a new one", e, bad.name)
        return empty
    if not isinstance(data, dict) or not isinstance(data.get("days"), dict):
        ext.log.error("ledger has unexpected structure, starting a new one")
        return empty
    return data


ledger = load()


def save() -> None:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    tmp = LEDGER.with_suffix(".tmp")
    tmp.write_text(json.dumps(ledger), "utf-8")
    tmp.replace(LEDGER)


def main_meter() -> str | None:
    return str(ext.settings.get("main_meter") or "") or state["auto_main"]


def today() -> Any:
    return datetime.now(state["tz"]).date()


async def publish() -> None:
    t = el.totals(ledger, today(), main_meter())
    values: dict[str, Any] = {
        k: t[k] for k in ("today_kwh", "today_cost", "month_kwh", "month_cost", "year_kwh", "year_cost")
    }
    values["w"] = round(state["w"], 1)
    values["price"] = round(state["price"], 4)
    await ext.state("usage", values)
    if values != state.get("pub"):
        state["pub"] = dict(values)
        await ext.changed("usage", "today")


async def close_day(day: Any) -> None:
    rows = ledger.get("days", {}).get(day.isoformat())
    if not rows:
        return
    main = main_meter()
    kwh = round(sum(v for d, v in rows["kwh"].items() if not main or d == main), 3)
    cost = round(sum(v for d, v in rows["cost"].items() if not main or d == main), 2)
    top = sorted(((state["names"].get(d, d), v) for d, v in rows["kwh"].items() if d != main), key=lambda x: -x[1])[:3]
    payload = {
        "day": day.strftime("%d.%m.%Y"),
        "kwh": kwh,
        "cost": cost,
        "currency": state["currency"],
        "top": ", ".join(f"{n} {v:.2f}" for n, v in top),
    }
    await ext.trigger("day_closed", payload)
    ext.log.info("day closed %s", payload)


async def tick() -> None:
    devs = await ext.call("devices.list")
    exclude = {x.strip() for x in str(ext.settings.get("exclude") or "").split(",") if x.strip()}
    ms = el.meters(devs, exclude)
    state["names"] = {d["id"]: d["name"] for d in ms}
    state["auto_main"] = el.auto_main(ms)
    state["price"] = el.unit_price(ext.settings)
    main = main_meter()
    state["w"] = sum(
        float((d.get("state") or {}).get("w") or 0)
        for d in ms
        if (not main or d["id"] == main) and d.get("available", True)
    )
    now = time.time()
    day = el.local_day(now, state["tz"])
    for d in ms:
        inc = el.delta(ledger.setdefault("meters", {}).setdefault(d["id"], {}), d, now)
        if inc > 0:
            el.record(ledger, day, d["id"], inc, state["price"])
    closed = ledger.get("closed")
    if closed and closed < day.isoformat():
        await close_day(day - timedelta(days=1))
    ledger["closed"] = day.isoformat()
    el.prune(ledger, day)
    save()
    await publish()


@ext.on_start
async def start() -> None:
    try:
        home = await ext.call("home")
        state["tz"] = ZoneInfo(home.get("timezone") or "Europe/Helsinki")
        state["currency"] = home.get("currency") or "EUR"
    except Exception as e:
        ext.log.warning("home info unavailable: %s", e)


@ext.loop
async def loop() -> None:
    while True:
        try:
            await tick()
        except Exception as e:
            ext.log.error("energy tick failed: %s", e)
        await asyncio.sleep(POLL)


def _period_total(period: str) -> tuple[float, float]:
    t = el.totals(ledger, today(), main_meter())
    key = period if period in ("today", "yesterday", "month", "year") else "today"
    return t[f"{key}_kwh"], t[f"{key}_cost"]


@ext.block("usage_above")
async def usage_above(params: dict, tok: dict, dry: bool) -> dict:
    kwh, _ = _period_total(str(params.get("span") or "today"))
    limit = float(params.get("value") or 0)
    ok = kwh > limit
    return {
        "outs": [[0 if ok else 1]],
        "trace": {"s": "ok" if ok else "no", "m": "ext_value", "p": {"value": kwh, "target": limit}},
    }


@ext.block("cost_above")
async def cost_above(params: dict, tok: dict, dry: bool) -> dict:
    _, cost = _period_total(str(params.get("span") or "today"))
    limit = float(params.get("value") or 0)
    ok = cost > limit
    return {
        "outs": [[0 if ok else 1]],
        "trace": {"s": "ok" if ok else "no", "m": "ext_value", "p": {"value": cost, "target": limit}},
    }


def L(uk: str, ru: str, en: str) -> dict[str, str]:
    return {"uk": uk, "ru": ru, "en": en}


def stat(label: dict[str, str], value: float | None, unit: str, digits: int = 2) -> dict[str, Any]:
    return {"label": label, "value": value, "unit": unit, "digits": digits}


def days_bars(label: dict[str, str], days: list[tuple[str, float]]) -> dict[str, Any]:
    return {
        "type": "bars",
        "label": label,
        "values": [v for _, v in days],
        "labels": [f"{k[8:10]}.{k[5:7]}" for k, _ in days],
        "unit": "kWh",
        "digits": 2,
        "series": [
            {"label": L("За добу", "За сутки", "Per day"), "color": "amber"},
            {
                "label": L("Сьогодні, день не завершено", "Сегодня, день не закончен", "Today, day in progress"),
                "color": "frost",
            },
        ],
        "kinds": [0] * (len(days) - 1) + [1],
    }


@ext.page("usage")
async def page_usage(params: dict) -> dict:
    t = el.totals(ledger, today(), main_meter())
    cur = state["currency"]
    blocks: list[dict[str, Any]] = [
        {
            "type": "stats",
            "items": [
                stat(L("Сьогодні", "Сегодня", "Today"), t["today_kwh"], "kWh"),
                stat(L("Сьогодні, вартість", "Сегодня, стоимость", "Today, cost"), t["today_cost"], cur),
                stat(L("Місяць", "Месяц", "Month"), t["month_kwh"], "kWh", 1),
                stat(L("Місяць, вартість", "Месяц, стоимость", "Month, cost"), t["month_cost"], cur),
                stat(L("Рік", "Год", "Year"), t["year_kwh"], "kWh", 1),
                stat(L("Зараз", "Сейчас", "Now"), round(state["w"]), "W", 0),
            ],
        }
    ]
    blocks.append(
        days_bars(
            L("Споживання за 30 днів, кВт·год", "Потребление за 30 дней, кВт·ч", "Usage for 30 days, kWh"),
            el.daily(ledger, today(), 30, main_meter()),
        )
    )
    rows = el.by_device(ledger, today(), "month")
    blocks.append(
        {
            "type": "list",
            "label": L("Пристрої за місяць", "Устройства за месяц", "Devices this month"),
            "items": [
                {
                    "text": state["names"].get(d, d),
                    "values": [{"value": k, "unit": "kWh", "digits": 2}, {"value": c, "unit": cur, "digits": 2}],
                }
                for d, k, c in rows[:20]
            ],
        }
    )
    return {"blocks": blocks, "updated": time.time()}


@ext.page("today")
async def page_today(params: dict) -> dict:
    t = el.totals(ledger, today(), main_meter())
    cur = state["currency"]
    return {
        "blocks": [
            {
                "type": "stats",
                "items": [
                    stat(L("Сьогодні", "Сегодня", "Today"), t["today_kwh"], "kWh"),
                    stat(L("Вартість", "Стоимость", "Cost"), t["today_cost"], cur),
                    stat(L("Місяць", "Месяц", "Month"), t["month_cost"], cur),
                ],
            },
            days_bars(
                L("30 днів, кВт·год", "30 дней, кВт·ч", "30 days, kWh"), el.daily(ledger, today(), 30, main_meter())
            ),
        ]
    }


if __name__ == "__main__":
    ext.run()
