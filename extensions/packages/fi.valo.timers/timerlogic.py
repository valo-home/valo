"""Таймеры и будильники без MQTT: разбор настроек, дни недели, расчет следующего срабатывания."""

import hashlib
import re
from datetime import date, datetime, time, timedelta
from typing import Any

DAY_NAMES = {
    0: ("пн", "mon", "mo", "понедельник", "понеділок", "monday"),
    1: ("вт", "tue", "tu", "вторник", "вівторок", "tuesday"),
    2: ("ср", "wed", "we", "среда", "середа", "wednesday"),
    3: ("чт", "thu", "th", "четверг", "четвер", "thursday"),
    4: ("пт", "fri", "fr", "пятница", "пʼятниця", "п'ятниця", "friday"),
    5: ("сб", "sat", "sa", "суббота", "субота", "saturday"),
    6: ("вс", "нд", "sun", "su", "воскресенье", "неділя", "sunday"),
}
LOOKUP = {n: i for i, names in DAY_NAMES.items() for n in names}
WORKDAYS = ("рабочие", "робочі", "workdays", "work")
OFFDAYS = ("выходные", "вихідні", "weekends", "offdays", "off")
EVERY = ("", "все", "всі", "ежедневно", "щодня", "daily", "every", "*")
SHORT = {
    "uk": ["пн", "вт", "ср", "чт", "пт", "сб", "нд"],
    "ru": ["пн", "вт", "ср", "чт", "пт", "сб", "вс"],
    "en": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
}
DAY_WORDS = {
    "work": {"uk": "робочі дні", "ru": "рабочие дни", "en": "workdays"},
    "off": {"uk": "вихідні", "ru": "выходные", "en": "weekends"},
    "every": {"uk": "щодня", "ru": "ежедневно", "en": "daily"},
}
TRANSLIT = dict(
    zip(
        "абвгґдеєжзиіїйклмнопрстуфхцчшщъыьэюяё",
        [
            *("a", "b", "v", "g", "g", "d", "e", "ie", "zh", "z", "y", "i", "i", "i", "k", "l", "m", "n", "o"),
            *("p", "r", "s", "t", "u", "f", "kh", "ts", "ch", "sh", "shch", "-", "y", "-", "e", "iu", "ia", "e"),
        ],
        strict=True,
    )
)
MAX_MINUTES = 24 * 60


def slug(name: str, prefix: str) -> str:
    low = name.strip().lower()
    s = "".join(TRANSLIT.get(ch, ch) for ch in low).replace("-", "")
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")[:24]
    if not s:
        s = hashlib.sha1(low.encode()).hexdigest()[:8]
    return f"{prefix}_{s}"


def parse_timers(text: str, rejected: list[str] | None = None) -> list[dict[str, Any]]:
    """Строки Название=минуты. Неразобранные строки и повторы добавляются в rejected."""
    out, seen = [], set()
    bad = rejected if rejected is not None else []
    for line in (text or "").splitlines():
        name, sep, rest = line.partition("=")
        name = name.strip()
        if not name:
            continue
        try:
            minutes = float(rest.strip().replace(",", ".")) if sep and rest.strip() else 10.0
        except ValueError:
            bad.append(line.strip())
            continue
        tid = slug(name, "t")
        if tid in seen or not 0 < minutes <= MAX_MINUTES:
            bad.append(line.strip())
            continue
        seen.add(tid)
        out.append({"id": tid, "name": name, "minutes": minutes})
    return out


def parse_time(s: str) -> time | None:
    m = re.fullmatch(r"\s*(\d{1,2})[:.](\d{2})\s*", s or "")
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        return None
    return time(int(m.group(1)), int(m.group(2)))


def parse_days(spec: str) -> tuple[str, set[int]] | None:
    """Режим и дни: ("days", {0..6}), ("work", set()) или ("off", set()). None, если строка не разобрана."""
    s = (spec or "").strip().lower()
    if s in EVERY:
        return "days", set(range(7))
    if s in WORKDAYS:
        return "work", set()
    if s in OFFDAYS:
        return "off", set()
    days: set[int] = set()
    for part in re.split(r"[,\s;]+", s):
        if not part:
            continue
        a, sep, b = part.partition("-")
        if sep and a in LOOKUP and b in LOOKUP:
            i, j = LOOKUP[a], LOOKUP[b]
            days.update(range(i, j + 1) if i <= j else [*range(i, 7), *range(j + 1)])
        elif part in LOOKUP:
            days.add(LOOKUP[part])
        elif part.isdigit() and 1 <= int(part) <= 7:
            days.add(int(part) - 1)
        else:
            return None
    return ("days", days) if days else None


def parse_alarms(text: str, rejected: list[str] | None = None) -> list[dict[str, Any]]:
    """Строки Название=ЧЧ:ММ дни. Неразобранные строки и повторы добавляются в rejected."""
    out, seen = [], set()
    bad = rejected if rejected is not None else []
    for line in (text or "").splitlines():
        name, sep, rest = line.partition("=")
        name = name.strip()
        if not name and not line.strip():
            continue
        when, _, days = rest.strip().partition(" ")
        if not name or not sep or parse_time(when) is None or parse_days(days) is None:
            bad.append(line.strip())
            continue
        aid = slug(name, "a")
        if aid in seen:
            bad.append(line.strip())
            continue
        seen.add(aid)
        out.append({"id": aid, "name": name, "time": when.strip(), "days": days.strip()})
    return out


def day_ok(mode: str, days: set[int], d: date, is_workday: Any) -> bool:
    if mode == "work":
        return bool(is_workday(d))
    if mode == "off":
        return not is_workday(d)
    return d.weekday() in days


def next_alarm(now: datetime, hhmm: str, spec: str, is_workday: Any, horizon: int = 14) -> datetime | None:
    t, parsed = parse_time(hhmm), parse_days(spec)
    if t is None or parsed is None:
        return None
    mode, days = parsed
    for i in range(horizon + 1):
        d = now.date() + timedelta(days=i)
        at = datetime.combine(d, t, now.tzinfo)
        if at > now and day_ok(mode, days, d, is_workday):
            return at
    return None


def due(last: datetime, now: datetime, hhmm: str, spec: str, is_workday: Any) -> bool:
    """Будильник срабатывает, если его время попало в промежуток (last, now]."""
    t, parsed = parse_time(hhmm), parse_days(spec)
    if t is None or parsed is None or now <= last:
        return False
    mode, days = parsed
    d = last.date()
    while d <= now.date():
        at = datetime.combine(d, t, now.tzinfo)
        if last < at <= now and day_ok(mode, days, d, is_workday):
            return True
        d += timedelta(days=1)
    return False


def fmt_days(spec: str, lang: str) -> str:
    """Дни будильника для показа: короткие названия через запятую, три и более подряд диапазоном."""
    parsed = parse_days(spec)
    if parsed is None:
        return (spec or "").strip()
    mode, days = parsed
    words = DAY_WORDS.get("every" if mode == "days" and len(days) == 7 else mode)
    if words:
        return words.get(lang) or words["en"]
    names = SHORT.get(lang, SHORT["en"])
    runs: list[list[int]] = []
    for d in sorted(days):
        if runs and d == runs[-1][-1] + 1:
            runs[-1].append(d)
        else:
            runs.append([d])
    return ", ".join(f"{names[r[0]]}-{names[r[-1]]}" if len(r) >= 3 else ", ".join(names[x] for x in r) for r in runs)


def fmt_next(at: datetime | None, now: datetime, lang: str) -> str:
    if at is None:
        return ""
    if at.date() == now.date():
        return f"{at:%H:%M}"
    return f"{SHORT.get(lang, SHORT['en'])[at.weekday()]} {at:%H:%M}"


def remaining_min(ends: float | None, now: float) -> int:
    if not ends or ends <= now:
        return 0
    return int(-(-(ends - now) // 60))
