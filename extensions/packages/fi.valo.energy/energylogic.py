"""Учет энергии: приращения счетчиков, интегрирование мощности, стоимость, суммы по периодам."""

from datetime import date, datetime, timedelta
from typing import Any

MAX_STEP_KWH = 50.0
MAX_GAP_S = 600.0


def meters(devices: list[dict[str, Any]], exclude: set[str]) -> list[dict[str, Any]]:
    out = []
    for d in devices:
        if d.get("id") in exclude or d.get("source") == "ext":
            continue
        caps = {c.get("id") for c in d.get("caps") or []}
        if "kwh" in caps or "w" in caps:
            out.append(d)
    return out


def auto_main(meters: list[dict[str, Any]]) -> str | None:
    """Если среди счетчиков ровно одно устройство вида meter, это общий счетчик дома."""
    main = [d["id"] for d in meters if d.get("kind") == "meter"]
    return main[0] if len(main) == 1 else None


def delta(state: dict[str, Any], d: dict[str, Any], ts: float) -> float:
    """Приращение кВт·ч устройства с прошлого опроса. state хранит last_kwh, last_ts, last_w по устройству."""
    st = d.get("state") or {}
    kwh, w = st.get("kwh"), st.get("w")
    inc = 0.0
    if isinstance(kwh, (int, float)) and not isinstance(kwh, bool):
        last = state.get("last_kwh")
        if last is not None:
            step = kwh - last if kwh >= last else kwh
            inc = step if 0 <= step <= MAX_STEP_KWH else 0.0
        state["last_kwh"] = float(kwh)
    elif isinstance(w, (int, float)) and not isinstance(w, bool) and d.get("available", True):
        last_ts, last_w = state.get("last_ts"), state.get("last_w")
        dt = ts - last_ts if last_ts is not None else 0.0
        if last_w is not None and 0 < dt <= MAX_GAP_S:
            inc = (last_w + w) / 2 * dt / 3600 / 1000
    if isinstance(w, (int, float)) and not isinstance(w, bool):
        state["last_w"] = float(w)
    state["last_ts"] = ts
    return round(inc, 6)


def unit_price(settings: dict[str, Any]) -> float:
    """Цена кВт·ч: тариф продавца плюс передача сетевой компании."""
    return float(settings.get("fixed_price") or 0) + float(settings.get("transfer") or 0)


def record(ledger: dict[str, Any], day: date, dev: str, kwh: float, price: float) -> None:
    row = ledger.setdefault("days", {}).setdefault(day.isoformat(), {"kwh": {}, "cost": {}})
    row["kwh"][dev] = round(row["kwh"].get(dev, 0.0) + kwh, 6)
    row["cost"][dev] = round(row["cost"].get(dev, 0.0) + kwh * price, 6)


def prune(ledger: dict[str, Any], today: date, keep_days: int = 800) -> None:
    edge = (today - timedelta(days=keep_days)).isoformat()
    ledger["days"] = {k: v for k, v in ledger.get("days", {}).items() if k >= edge}


def _sum(rows: list[dict[str, Any]], key: str, devs: set[str] | None) -> float:
    return round(sum(v for r in rows for d, v in r.get(key, {}).items() if devs is None or d in devs), 4)


def totals(ledger: dict[str, Any], today: date, main: str | None = None) -> dict[str, float]:
    days = ledger.get("days", {})
    devs = {main} if main else None

    def pick(pred) -> list[dict[str, Any]]:
        return [v for k, v in days.items() if pred(date.fromisoformat(k))]

    periods = {
        "today": pick(lambda d: d == today),
        "yesterday": pick(lambda d: d == today - timedelta(days=1)),
        "month": pick(lambda d: (d.year, d.month) == (today.year, today.month)),
        "year": pick(lambda d: d.year == today.year),
    }
    out: dict[str, float] = {}
    for name, rows in periods.items():
        out[f"{name}_kwh"] = _sum(rows, "kwh", devs)
        out[f"{name}_cost"] = round(_sum(rows, "cost", devs), 2)
    return out


def by_device(ledger: dict[str, Any], today: date, period: str = "month") -> list[tuple[str, float, float]]:
    agg: dict[str, list[float]] = {}
    for k, row in ledger.get("days", {}).items():
        d = date.fromisoformat(k)
        ok = d == today if period == "today" else (d.year, d.month) == (today.year, today.month)
        if period == "year":
            ok = d.year == today.year
        if not ok:
            continue
        for dev, v in row.get("kwh", {}).items():
            agg.setdefault(dev, [0.0, 0.0])[0] += v
        for dev, v in row.get("cost", {}).items():
            agg.setdefault(dev, [0.0, 0.0])[1] += v
    return sorted(((d, round(a, 3), round(c, 2)) for d, (a, c) in agg.items()), key=lambda x: -x[1])


def daily(ledger: dict[str, Any], today: date, n: int = 30, main: str | None = None) -> list[tuple[str, float]]:
    devs = {main} if main else None
    out = []
    for i in range(n - 1, -1, -1):
        k = (today - timedelta(days=i)).isoformat()
        row = ledger.get("days", {}).get(k, {})
        out.append((k, _sum([row], "kwh", devs) if row else 0.0))
    return out


def local_day(ts: float, tz: Any) -> date:
    return datetime.fromtimestamp(ts, tz).date()
