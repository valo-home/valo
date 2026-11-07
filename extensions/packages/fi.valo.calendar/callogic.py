"""Рабочие дни, праздники Украины и Финляндии, разбор и развертка ICS без сети."""

import re
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

Names = dict[str, str]
MAX_OCCURRENCES = 5000
WEEKDAY = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}


def N(uk: str, ru: str, en: str, local: str = "") -> Names:
    return {"uk": uk, "ru": ru, "en": en, "local": local or en}


def easter_western(y: int) -> date:
    a, b, c = y % 19, y // 100, y % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    m = (32 + 2 * e + 2 * i - h - k) % 7
    n = (a + 11 * h + 22 * m) // 451
    month = (h + m - 7 * n + 114) // 31
    day = (h + m - 7 * n + 114) % 31 + 1
    return date(y, month, day)


def easter_orthodox(y: int) -> date:
    a, b, c = y % 4, y % 7, y % 19
    d = (19 * c + 15) % 30
    e = (2 * a + 4 * b - d + 34) % 7
    month = (d + e + 114) // 31
    day = (d + e + 114) % 31 + 1
    return date(y, month, day) + timedelta(days=(y // 100) - (y // 400) - 2)


def _weekday_between(y: int, month: int, first: int, last: int, wd: int) -> date:
    for d in range(first, last + 1):
        x = date(y, month, d)
        if x.weekday() == wd:
            return x
    raise ValueError("no weekday in range")


def holidays_ua(y: int) -> dict[date, Names]:
    e = easter_orthodox(y)
    return {
        date(y, 1, 1): N("Новий рік", "Новый год", "New Year's Day", "Новий рік"),
        date(y, 3, 8): N("Міжнародний жіночий день", "Международный женский день", "International Women's Day"),
        e: N("Великдень", "Пасха", "Easter", "Великдень"),
        e + timedelta(days=49): N("Трійця", "Троица", "Trinity", "Трійця"),
        date(y, 5, 1): N("День праці", "День труда", "Labour Day", "День праці"),
        date(y, 5, 8): N("День пам'яті та перемоги", "День памяти и победы", "Remembrance and Victory Day"),
        date(y, 6, 28): N("День Конституції", "День Конституции", "Constitution Day", "День Конституції"),
        date(y, 7, 15): N("День Української Державності", "День украинской государственности", "Statehood Day"),
        date(y, 8, 24): N("День Незалежності", "День независимости", "Independence Day", "День Незалежності"),
        date(y, 10, 1): N("День захисників і захисниць", "День защитников и защитниц", "Defenders Day"),
        date(y, 12, 25): N("Різдво Христове", "Рождество Христово", "Christmas Day", "Різдво Христове"),
    }


def holidays_fi(y: int) -> dict[date, Names]:
    e = easter_western(y)
    return {
        date(y, 1, 1): N("Новий рік", "Новый год", "New Year's Day", "Uudenvuodenpäivä"),
        date(y, 1, 6): N("Водохреще", "Крещение", "Epiphany", "Loppiainen"),
        e - timedelta(days=2): N("Страсна п'ятниця", "Страстная пятница", "Good Friday", "Pitkäperjantai"),
        e: N("Великдень", "Пасха", "Easter Sunday", "Pääsiäispäivä"),
        e + timedelta(days=1): N("Великодній понеділок", "Пасхальный понедельник", "Easter Monday", "2. pääsiäispäivä"),
        date(y, 5, 1): N("Ваппу", "Ваппу", "May Day", "Vappu"),
        e + timedelta(days=39): N("Вознесіння", "Вознесение", "Ascension Day", "Helatorstai"),
        e + timedelta(days=49): N("Трійця", "Троица", "Whit Sunday", "Helluntaipäivä"),
        _weekday_between(y, 6, 19, 25, 4): N("Переддень Юханнуса", "Канун Юханнуса", "Midsummer Eve", "Juhannusaatto"),
        _weekday_between(y, 6, 20, 26, 5): N("Юханнус", "Юханнус", "Midsummer Day", "Juhannuspäivä"),
        _all_saints(y): N("День усіх святих", "День всех святых", "All Saints' Day", "Pyhäinpäivä"),
        date(y, 12, 6): N("День незалежності", "День независимости", "Independence Day", "Itsenäisyyspäivä"),
        date(y, 12, 24): N("Святвечір", "Сочельник", "Christmas Eve", "Jouluaatto"),
        date(y, 12, 25): N("Різдво", "Рождество", "Christmas Day", "Joulupäivä"),
        date(y, 12, 26): N("День святого Стефана", "День святого Стефана", "St. Stephen's Day", "Tapaninpäivä"),
    }


def _all_saints(y: int) -> date:
    for d in [date(y, 10, 31) + timedelta(days=i) for i in range(7)]:
        if d.weekday() == 5:
            return d
    raise ValueError("no saturday")


def holidays(country: str, y: int) -> dict[date, Names]:
    if country == "UA":
        return holidays_ua(y)
    if country == "FI":
        return holidays_fi(y)
    return {}


def holiday(country: str, d: date) -> Names | None:
    return holidays(country, d.year).get(d)


def holidays_off(country: str, mode: str) -> bool:
    """В Украине во время военного положения праздники рабочие, поэтому auto для UA выключает выходные."""
    if mode == "yes":
        return True
    if mode == "no":
        return False
    return country == "FI"


def parse_dates(text: str) -> set[date]:
    out: set[date] = set()
    for part in re.split(r"[,;\s]+", text or ""):
        if not part:
            continue
        a, sep, b = part.partition("..")
        try:
            start = date.fromisoformat(a)
            end = date.fromisoformat(b) if sep else start
        except ValueError:
            continue
        if end < start or (end - start).days > 400:
            continue
        out.update(start + timedelta(days=i) for i in range((end - start).days + 1))
    return out


class Workdays:
    def __init__(self, country: str, mode: str, extra_off: str = "", extra_work: str = "") -> None:
        self.country = country if country in ("UA", "FI") else ""
        self.off = holidays_off(self.country, mode)
        self.extra_off = parse_dates(extra_off)
        self.extra_work = parse_dates(extra_work)

    def is_workday(self, d: date) -> bool:
        if d in self.extra_work:
            return True
        if d in self.extra_off or d.weekday() >= 5:
            return False
        return not (self.off and holiday(self.country, d))

    def holiday(self, d: date) -> Names | None:
        return holiday(self.country, d) if self.country else None

    def next_holiday(self, d: date, days: int = 400) -> tuple[date, Names] | None:
        if not self.country:
            return None
        for i in range(days):
            x = d + timedelta(days=i)
            h = holiday(self.country, x)
            if h:
                return x, h
        return None

    def upcoming(self, d: date, n: int = 6) -> list[tuple[date, Names]]:
        rows = sorted((k, v) for y in (d.year, d.year + 1) for k, v in holidays(self.country, y).items() if k >= d)
        return rows[:n]


def unfold(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        elif raw:
            lines.append(raw)
    return lines


def _unescape(v: str) -> str:
    return re.sub(r"\\([\\;,nN])", lambda m: "\n" if m.group(1) in "nN" else m.group(1), v)


def _prop(line: str) -> tuple[str, dict[str, str], str]:
    head, _, value = line.partition(":")
    parts = head.split(";")
    params = {}
    for p in parts[1:]:
        k, _, v = p.partition("=")
        params[k.upper()] = v.strip('"')
    return parts[0].upper(), params, value


def _zone(name: str | None, default: tzinfo) -> tzinfo:
    if not name:
        return default
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError, ValueError:
        return default


def _when(value: str, params: dict[str, str], default: tzinfo) -> tuple[datetime, bool]:
    v = value.strip()
    if params.get("VALUE") == "DATE" or re.fullmatch(r"\d{8}", v):
        d = datetime.strptime(v[:8], "%Y%m%d").date()
        return datetime.combine(d, time(0), default), True
    if v.endswith("Z"):
        return datetime.strptime(v[:15], "%Y%m%dT%H%M%S").replace(tzinfo=UTC), False
    return datetime.strptime(v[:15], "%Y%m%dT%H%M%S").replace(tzinfo=_zone(params.get("TZID"), default)), False


def _duration(v: str) -> timedelta:
    m = re.fullmatch(r"([+-])?P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", v.strip())
    if not m:
        return timedelta(0)
    sign = -1 if m.group(1) == "-" else 1
    w, d, h, mi, s = (int(x or 0) for x in m.groups()[1:])
    return sign * timedelta(weeks=w, days=d, hours=h, minutes=mi, seconds=s)


def _close(cur: dict[str, Any], default: tzinfo, stats: dict[str, int]) -> dict[str, Any] | None:
    if cur.get("bad") or "start" not in cur:
        stats["skipped"] += 1
        return None
    if cur.get("status") == "CANCELLED":
        return None
    if "end" not in cur:
        cur["end"] = cur["start"] + (
            cur.pop("duration", None) or (timedelta(days=1) if cur["all_day"] else timedelta(0))
        )
    rule = cur.get("rrule")
    if rule is not None:
        try:
            ok = int(rule.get("INTERVAL") or 1) > 0
            _until(rule, default)
        except ValueError:
            ok = False
        freq = rule.get("FREQ", "")
        if not ok or freq not in ("DAILY", "WEEKLY", "MONTHLY", "YEARLY") or not _supported(rule, freq, cur["start"]):
            stats["unsupported"] += 1
            cur.pop("rrule")
    return cur


def parse_ics(text: str, default: tzinfo, stats: dict[str, int] | None = None) -> list[dict[str, Any]]:
    """Каждое событие разбирается отдельно: событие с ошибкой пропускается, неподдерживаемое правило повтора
    оставляет только первое вхождение. Счетчики skipped и unsupported пишутся в stats."""
    st = stats if stats is not None else {}
    st.update(skipped=0, unsupported=0)
    events: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None
    for line in unfold(text):
        name, params, value = _prop(line)
        if name == "BEGIN" and value.upper() == "VEVENT":
            cur = {"exdates": set(), "summary": ""}
            continue
        if name == "END" and value.upper() == "VEVENT" and cur is not None:
            ev = _close(cur, default, st)
            if ev is not None:
                events.append(ev)
            cur = None
            continue
        if cur is None:
            continue
        try:
            _apply(cur, name, params, value, default)
        except ValueError, KeyError:
            cur["bad"] = True
    masters = {e.get("uid"): e for e in events if "rrule" in e}
    for e in events:
        if "recurrence" in e and e.get("uid") in masters:
            masters[e["uid"]]["exdates"].add(e["recurrence"])
    return events


def _apply(cur: dict[str, Any], name: str, params: dict[str, str], value: str, default: tzinfo) -> None:
    if name == "DTSTART":
        cur["start"], cur["all_day"] = _when(value, params, default)
    elif name == "DTEND":
        cur["end"], _ = _when(value, params, default)
    elif name == "DURATION":
        cur["duration"] = _duration(value)
    elif name == "SUMMARY":
        cur["summary"] = _unescape(value).strip()
    elif name == "UID":
        cur["uid"] = value
    elif name == "STATUS":
        cur["status"] = value.upper()
    elif name == "RRULE":
        cur["rrule"] = {k.upper(): v for k, _, v in (p.partition("=") for p in value.split(";")) if k}
    elif name == "EXDATE":
        for v in value.split(","):
            cur["exdates"].add(_when(v, params, default)[0])
    elif name == "RECURRENCE-ID":
        cur["recurrence"] = _when(value, params, default)[0]


def _until(rule: dict[str, str], default: tzinfo) -> datetime | None:
    if "UNTIL" not in rule:
        return None
    dt, all_day = _when(rule["UNTIL"], {}, default)
    return dt + timedelta(days=1) - timedelta(seconds=1) if all_day else dt


def _add_months(d: datetime, months: int) -> datetime | None:
    m = d.month - 1 + months
    y, m = d.year + m // 12, m % 12 + 1
    try:
        return d.replace(year=y, month=m)
    except ValueError:
        return None


def _period(freq: str, interval: int) -> timedelta | None:
    return {"DAILY": timedelta(days=interval), "WEEKLY": timedelta(weeks=interval)}.get(freq)


def _batch(freq: str, s0: datetime, i: int, interval: int, days: list[int]) -> list[datetime]:
    if freq == "DAILY":
        return [s0 + timedelta(days=i * interval)]
    if freq == "WEEKLY":
        week = s0 - timedelta(days=s0.weekday()) + timedelta(weeks=i * interval)
        return [x for x in sorted(week + timedelta(days=wd) for wd in (days or [s0.weekday()])) if x >= s0]
    x = _add_months(s0, i * interval * (12 if freq == "YEARLY" else 1))
    return [x] if x else []


def _supported(rule: dict[str, str], freq: str, s0: datetime) -> bool:
    for k, v in rule.items():
        if k in ("FREQ", "INTERVAL", "COUNT", "UNTIL", "WKST"):
            continue
        if k == "BYDAY" and freq == "WEEKLY" and all(x[-2:] in WEEKDAY and len(x) == 2 for x in v.split(",")):
            continue
        if k == "BYMONTHDAY" and v == str(s0.day):
            continue
        if k == "BYMONTH" and v == str(s0.month):
            continue
        return False
    return True


def _starts(e: dict[str, Any], start: datetime, end: datetime, default: tzinfo) -> list[datetime]:
    s0: datetime = e["start"]
    rule = e.get("rrule")
    freq = (rule or {}).get("FREQ", "")
    if not rule:
        return [s0]
    interval = max(int(rule.get("INTERVAL") or 1), 1)
    count = int(rule["COUNT"]) if rule.get("COUNT", "").isdigit() else None
    until = _until(rule, default)
    days = [WEEKDAY[x[-2:]] for x in rule.get("BYDAY", "").split(",") if x[-2:] in WEEKDAY]
    length = e["end"] - s0
    i = 0
    step = _period(freq, interval)
    if count is None and step is not None and start - length > s0:
        i = max(int((start - length - s0) / step) - 1, 0)
    out: list[datetime] = []
    n = 0
    for _ in range(MAX_OCCURRENCES):
        batch = _batch(freq, s0, i, interval, days)
        i += 1
        for x in batch:
            n += 1
            if (until and x > until) or (count is not None and n > count) or x >= end:
                return out
            out.append(x)
    return out


def expand(events: list[dict[str, Any]], start: datetime, end: datetime, default: tzinfo) -> list[dict[str, Any]]:
    """События, пересекающие [start, end), по времени начала."""
    out = []
    for e in events:
        length = e["end"] - e["start"]
        try:
            starts = _starts(e, start, end, default)
        except ValueError, OverflowError:
            starts = [e["start"]]
        for s in starts:
            if s in e["exdates"]:
                continue
            f = s + length
            if f > start and s < end:
                out.append({"title": e["summary"], "start": s, "end": f, "all_day": e["all_day"]})
    return sorted(out, key=lambda x: (x["start"], x["title"]))


def active(occ: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    return [o for o in occ if o["start"] <= now < o["end"]]


def on_day(occ: list[dict[str, Any]], d: date, tz: tzinfo) -> list[dict[str, Any]]:
    a = datetime.combine(d, time(0), tz)
    b = a + timedelta(days=1)
    return [o for o in occ if o["start"] < b and o["end"] > a]


def matches(title: str, contains: str) -> bool:
    return not contains.strip() or contains.strip().lower() in title.lower()
