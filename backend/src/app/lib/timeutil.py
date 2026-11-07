import math
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from zoneinfo import ZoneInfo

_RANGES = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 7))
_NAMES = {"sun": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6}


def zone(name: str | None) -> tzinfo:
    try:
        return ZoneInfo(name or "UTC")
    except Exception:
        return UTC


def _field(spec: str, lo: int, hi: int) -> set[int] | None:
    if spec == "*":
        return None
    out: set[int] = set()
    for part in spec.lower().split(","):
        rng, _, step = part.partition("/")
        if rng == "*":
            a, b = lo, hi
        elif "-" in rng:
            a, b = (int(_NAMES.get(x, x)) for x in rng.split("-", 1))
        else:
            a = b = int(_NAMES.get(rng, rng))
        if not (lo <= a <= hi and lo <= b <= hi):
            raise ValueError(part)
        out.update(range(a, b + 1, int(step or 1)))
    return out


def cron_parse(expr: str) -> list[set[int] | None]:
    parts = expr.split()
    if len(parts) != 5:
        raise ValueError(expr)
    return [_field(p, *r) for p, r in zip(parts, _RANGES, strict=True)]


def cron_match(expr: str, at: datetime) -> bool:
    mi, hr, dom, mon, dow = cron_parse(expr)
    if dow is not None and 7 in dow:
        dow = dow | {0}
    wd = (at.weekday() + 1) % 7
    ok = lambda s, v: s is None or v in s
    if not (ok(mi, at.minute) and ok(hr, at.hour) and ok(mon, at.month)):
        return False
    if dom is not None and dow is not None:
        return at.day in dom or wd in dow
    return ok(dom, at.day) and ok(dow, wd)


def sun(day: date, lat: float, lon: float, tz: tzinfo) -> tuple[str, datetime | None, datetime | None]:
    g = 2 * math.pi / 365 * (day.timetuple().tm_yday - 1)
    eqt = 229.18 * (
        0.000075
        + 0.001868 * math.cos(g)
        - 0.032077 * math.sin(g)
        - 0.014615 * math.cos(2 * g)
        - 0.040849 * math.sin(2 * g)
    )
    decl = (
        0.006918
        - 0.399912 * math.cos(g)
        + 0.070257 * math.sin(g)
        - 0.006758 * math.cos(2 * g)
        + 0.000907 * math.sin(2 * g)
        - 0.002697 * math.cos(3 * g)
        + 0.00148 * math.sin(3 * g)
    )
    la = math.radians(lat)
    cos_h = math.cos(math.radians(90.833)) / (math.cos(la) * math.cos(decl)) - math.tan(la) * math.tan(decl)
    if cos_h > 1:
        return "night", None, None
    if cos_h < -1:
        return "day", None, None
    h = math.degrees(math.acos(cos_h))
    base = datetime.combine(day, time(0), tzinfo=UTC)
    rise = base + timedelta(minutes=720 - 4 * (lon + h) - eqt)
    sets = base + timedelta(minutes=720 - 4 * (lon - h) - eqt)
    return "normal", rise.astimezone(tz), sets.astimezone(tz)


def hm(value: str) -> time:
    h, m = value.split(":")[:2]
    return time(int(h), int(m))


def in_window(now: time, start: time, end: time) -> bool:
    return start <= now < end if start <= end else now >= start or now < end
