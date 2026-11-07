"""Контроль розеток: перегрузка, отключение в простое, учет за сегодня по часам. Без сети."""

import math
import re
from datetime import date, timedelta
from typing import Any

MAX_STEP_KWH = 50.0
MAX_GAP_S = 600.0
HOLD_S = 30.0
KEEP_DAYS = 31


def num(v: Any) -> float | None:
    """Число из недоверенных данных устройства, иначе None."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    x = float(v)
    return x if math.isfinite(x) else None


def parse_ids(text: Any) -> list[str]:
    out: list[str] = []
    for x in re.split(r"[\s,;]+", str(text or "")):
        if x and x not in out:
            out.append(x)
    return out


def switchable(dev: dict[str, Any]) -> bool:
    """Устройство с измерением мощности и записываемым включением."""
    caps = {c.get("id"): c for c in dev.get("caps") or [] if isinstance(c, dict)}
    on = caps.get("on")
    return "w" in caps and isinstance(on, dict) and "w" in str(on.get("access") or "")


def plugs(devices: Any, own: str) -> list[dict[str, Any]]:
    out = []
    for d in devices if isinstance(devices, list) else []:
        if not isinstance(d, dict) or not isinstance(d.get("id"), str) or d.get("extId") == own or d.get("disabled"):
            continue
        if switchable(d):
            out.append(d)
    return out


def watch(dev: dict[str, Any], old: dict[str, Any] | None = None) -> dict[str, Any]:
    """Слежение за розеткой: последние значения и отметки времени порогов. Прежние отметки сохраняются."""
    old = old or {}
    st = dev.get("state") if isinstance(dev.get("state"), dict) else {}
    w = {
        "id": dev["id"],
        "name": str(dev.get("name") or dev["id"])[:80],
        "available": dev.get("available") is not False,
        "w": old.get("w"),
        "on": old.get("on"),
        "kwh": old.get("kwh"),
        "over_since": old.get("over_since"),
        "low_since": old.get("low_since"),
        "hold_until": old.get("hold_until", 0.0),
    }
    update(w, st)
    return w


def update(w: dict[str, Any], values: Any) -> None:
    if not isinstance(values, dict):
        return
    p = num(values.get("w"))
    if p is not None and p >= 0:
        w["w"] = p
    if isinstance(values.get("on"), bool):
        w["on"] = values["on"]
    k = num(values.get("kwh"))
    if k is not None and k >= 0:
        w["kwh"] = k


def overload(w: dict[str, Any], now: float, limit: float, delay: float) -> bool:
    """Мощность выше предела дольше задержки. Отметка начала сбрасывается, как только мощность опустилась."""
    p = w.get("w")
    if p is None or p <= limit or w.get("on") is False or not w.get("available", True):
        w["over_since"] = None
        return False
    if w.get("over_since") is None:
        w["over_since"] = now
    return now - w["over_since"] >= delay and now >= w.get("hold_until", 0.0)


def standby(w: dict[str, Any], now: float, low: float, minutes: float) -> bool:
    """Включенная розетка потребляет меньше порога дольше заданного числа минут."""
    p = w.get("w")
    if w.get("on") is not True or p is None or p >= low or not w.get("available", True):
        w["low_since"] = None
        return False
    if w.get("low_since") is None:
        w["low_since"] = now
    return now - w["low_since"] >= minutes * 60 and now >= w.get("hold_until", 0.0)


def tripped(w: dict[str, Any], now: float) -> None:
    w["over_since"] = None
    w["low_since"] = None
    w["hold_until"] = now + HOLD_S


def empty_day(day: date) -> dict[str, Any]:
    return {"day": day.isoformat(), "plugs": {}, "hours": [0.0] * 24}


def row(ledger: dict[str, Any], dev: str) -> dict[str, Any]:
    r = ledger["plugs"].setdefault(dev, {})
    r.setdefault("kwh", 0.0)
    r.setdefault("peak", 0.0)
    r.setdefault("on_s", 0.0)
    r.setdefault("trips", 0)
    return r


def roll(ledger: dict[str, Any], day: date, keep: int = KEEP_DAYS) -> bool:
    """Начать новый день: итоги прошлого уходят в историю, лишние дни удаляются."""
    if ledger.get("day") == day.isoformat():
        return False
    if ledger.get("day"):
        totals = {d: round(r.get("kwh", 0.0), 4) for d, r in ledger.get("plugs", {}).items()}
        ledger.setdefault("history", {})[ledger["day"]] = totals
    edge = (day - timedelta(days=keep)).isoformat()
    history = {k: v for k, v in ledger.get("history", {}).items() if k >= edge}
    meters = ledger.get("meters", {})
    ledger.clear()
    ledger.update(empty_day(day) | {"history": history, "meters": meters})
    return True


def advance(ledger: dict[str, Any], w: dict[str, Any], dt: float, hour: int) -> float:
    """Учесть интервал dt секунд. Прирост счетчика kwh важнее интегрирования мощности. Возвращает кВт·ч."""
    r = row(ledger, w["id"])
    m = ledger.setdefault("meters", {}).setdefault(w["id"], {})
    inc = 0.0
    kwh = w.get("kwh")
    if kwh is not None:
        last = m.get("last_kwh")
        if last is not None:
            step = kwh - last if kwh >= last else kwh
            inc = step if 0 <= step <= MAX_STEP_KWH else 0.0
        m["last_kwh"] = kwh
    elif w.get("w") is not None and w.get("available", True) and 0 < dt <= MAX_GAP_S:
        inc = w["w"] * dt / 3600 / 1000
    if w.get("w") is not None and w.get("available", True):
        r["peak"] = max(r["peak"], w["w"])
    if w.get("on") is True and w.get("available", True) and 0 < dt <= MAX_GAP_S:
        r["on_s"] += dt
    if inc > 0:
        r["kwh"] = round(r["kwh"] + inc, 6)
        ledger["hours"][min(max(hour, 0), 23)] = round(ledger["hours"][min(max(hour, 0), 23)] + inc, 6)
    return inc


def total_kwh(ledger: dict[str, Any]) -> float:
    return round(sum(r.get("kwh", 0.0) for r in ledger.get("plugs", {}).values()), 4)


def yesterday_kwh(ledger: dict[str, Any], day: date) -> float | None:
    totals = ledger.get("history", {}).get((day - timedelta(days=1)).isoformat())
    return round(sum(totals.values()), 4) if isinstance(totals, dict) else None


def _numbers(d: Any, none: bool = False) -> bool:
    return isinstance(d, dict) and all((none and v is None) or num(v) is not None for v in d.values())


def valid(ledger: Any) -> bool:
    """Проверка сохраненных итогов перед загрузкой."""
    if not isinstance(ledger, dict) or not isinstance(ledger.get("day"), str):
        return False
    groups = [ledger.get("plugs"), ledger.get("history", {}), ledger.get("meters", {})]
    if not all(isinstance(g, dict) for g in groups):
        return False
    plugs, history, meters = groups
    if not all(_numbers(r) for r in plugs.values()) or not all(_numbers(h) for h in history.values()):
        return False
    if not all(_numbers(m, none=True) for m in meters.values()):
        return False
    hours = ledger.get("hours")
    return isinstance(hours, list) and len(hours) == 24 and all(num(h) is not None for h in hours)
