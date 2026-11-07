"""Безопасность дома: датчики протечки, дыма, угарного газа и газа, инциденты и напоминания. Без сети."""

import math
import re
from datetime import date, datetime
from typing import Any

KINDS = ("leak", "smoke", "co", "gas")
LOW_BAT = 20
MAX_INCIDENTS = 50
TEST_GRACE_S = 120
REMIND_EVERY_DAYS = 7


def num(v: Any) -> float | None:
    """Число из недоверенных данных устройства, иначе None."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    x = float(v)
    return x if math.isfinite(x) else None


def parse_ids(text: Any) -> list[str]:
    """Id устройств из строки настройки через запятую, пробел или с новой строки, без повторов."""
    out: list[str] = []
    for x in re.split(r"[\s,;]+", str(text or "")):
        if x and x not in out:
            out.append(x)
    return out


def sensor_kinds(dev: dict[str, Any]) -> list[str]:
    caps = {c.get("id"): c for c in dev.get("caps") or [] if isinstance(c, dict)}
    return [k for k in KINDS if k in caps and caps[k].get("type", "bool") == "bool"]


def sensor(dev: dict[str, Any], old: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Описание датчика из записи devices.list. Прежние флаги тревоги и отметка проверки сохраняются."""
    did = dev.get("id")
    kinds = sensor_kinds(dev)
    if not isinstance(did, str) or not did or not kinds:
        return None
    st = dev.get("state") if isinstance(dev.get("state"), dict) else {}
    old = old or {}
    s = {
        "id": did,
        "name": str(dev.get("name") or did)[:80],
        "room": dev.get("roomId") if isinstance(dev.get("roomId"), str) else None,
        "kinds": kinds,
        "available": dev.get("available") is not False,
        "seen": dev.get("lastSeen") if isinstance(dev.get("lastSeen"), str) else None,
        "bat": num(st.get("bat")),
        "state": dict(old.get("state") or {}),
        "test_at": old.get("test_at"),
    }
    return s


def sensors(devices: Any, own: str, exclude: set[str]) -> list[dict[str, Any]]:
    """Датчики безопасности среди устройств дома, кроме устройств самого расширения и исключенных."""
    out = []
    for d in devices if isinstance(devices, list) else []:
        if not isinstance(d, dict) or d.get("id") in exclude or d.get("extId") == own or d.get("disabled"):
            continue
        if sensor_kinds(d):
            out.append(d)
    return out


def apply(s: dict[str, Any], values: Any, now: float) -> tuple[list[str], list[str]]:
    """Применить новые значения к датчику. Возвращает виды, где тревога началась и где закончилась."""
    raised: list[str] = []
    cleared: list[str] = []
    if not isinstance(values, dict):
        return raised, cleared
    if values.get("test") is True:
        s["test_at"] = now
    bat = num(values.get("bat"))
    if bat is not None:
        s["bat"] = bat
    for k in s["kinds"]:
        v = values.get(k)
        if not isinstance(v, bool):
            continue
        was = s["state"].get(k) is True
        s["state"][k] = v
        if v and not was:
            raised.append(k)
        elif was and not v:
            cleared.append(k)
    return raised, cleared


def active(s: dict[str, Any]) -> list[str]:
    return [k for k in s["kinds"] if s["state"].get(k) is True]


def is_test(s: dict[str, Any], kind: str, now: float) -> bool:
    """Дым сразу после нажатия кнопки проверки на датчике считается проверкой, а не пожаром."""
    at = s.get("test_at")
    return kind == "smoke" and isinstance(at, (int, float)) and 0 <= now - at <= TEST_GRACE_S


def open_incident(
    incidents: list[dict[str, Any]], s: dict[str, Any], kind: str, now: float, test: bool = False
) -> dict[str, Any]:
    seq = max((int(i.get("id") or 0) for i in incidents), default=0) + 1
    inc = {
        "id": seq,
        "ts": now,
        "device": s["id"],
        "name": s["name"],
        "room": s.get("room"),
        "kind": kind,
        "end": None,
        "acked": test,
        "test": test,
        "shutoff": [],
    }
    incidents.append(inc)
    del incidents[:-MAX_INCIDENTS]
    return inc


def restore(raw: Any) -> list[dict[str, Any]]:
    """Инциденты из сохраненного файла, записи неверного вида отбрасываются."""
    if not isinstance(raw, list):
        return []
    ok = [i for i in raw if isinstance(i, dict) and i.get("kind") in KINDS and num(i.get("ts")) is not None]
    for i in ok:
        if not isinstance(i.get("shutoff"), list):
            i["shutoff"] = []
    return ok[-MAX_INCIDENTS:]


def close_incidents(incidents: list[dict[str, Any]], dev: str, kind: str, now: float) -> int:
    n = 0
    for i in incidents:
        if i.get("device") == dev and i.get("kind") == kind and i.get("end") is None:
            i["end"] = now
            n += 1
    return n


def ack(incidents: list[dict[str, Any]]) -> int:
    n = 0
    for i in incidents:
        if not i.get("acked"):
            i["acked"] = True
            n += 1
    return n


def alarm_on(incidents: list[dict[str, Any]], sensors_: list[dict[str, Any]], now: float) -> bool:
    """Тревога держится, пока есть неподтвержденный инцидент или датчик еще в тревоге (кроме проверки дыма)."""
    if any(not i.get("acked") for i in incidents):
        return True
    return any(not is_test(s, k, now) for s in sensors_ for k in active(s))


def low_battery(s: dict[str, Any]) -> bool:
    return s.get("bat") is not None and s["bat"] < LOW_BAT


def warnings(sensors_: list[dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    out: list[tuple[str, dict[str, Any]]] = []
    for s in sensors_:
        if not s["available"]:
            out.append(("offline", s))
        if low_battery(s):
            out.append(("battery", s))
    return out


def test_age(tested: Any, today: date) -> int | None:
    """Сколько дней прошло с последней проверки датчиков дыма, None если проверки не было."""
    if not isinstance(tested, str):
        return None
    try:
        return (today - date.fromisoformat(tested)).days
    except ValueError:
        return None


def test_due(tested: Any, today: date, every: float) -> bool:
    age = test_age(tested, today)
    return age is None or age >= every


def remind(tested: Any, reminded: Any, today: date, every: float) -> bool:
    """Пора ли напомнить о проверке. Повтор раз в неделю, пока проверку не отметят."""
    if not test_due(tested, today, every):
        return False
    last = test_age(reminded, today)
    return last is None or last >= REMIND_EVERY_DAYS


def rank(s: dict[str, Any]) -> int:
    if active(s):
        return 0
    if not s["available"]:
        return 1
    if low_battery(s):
        return 2
    return 3


def counts(sensors_: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "sensors": len(sensors_),
        "active": sum(1 for s in sensors_ if active(s)),
        "warnings": len(warnings(sensors_)),
        **{k: sum(1 for s in sensors_ if k in s["kinds"]) for k in KINDS},
    }


def seen_text(seen: Any, tz: Any, now: datetime) -> str:
    """Время последней связи: ЧЧ:ММ сегодня, ДД.ММ ЧЧ:ММ раньше."""
    if not isinstance(seen, str) or not seen:
        return ""
    try:
        t = datetime.fromisoformat(seen.replace("Z", "+00:00")).astimezone(tz)
    except ValueError:
        return ""
    return t.strftime("%H:%M") if t.date() == now.date() else t.strftime("%d.%m %H:%M")
