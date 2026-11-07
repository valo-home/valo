"""Open-Meteo без сети: адреса запросов, разбор ответа, коды погоды, окна прогноза, демо данные."""

import math
import urllib.parse
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

FORECAST = "https://api.open-meteo.com/v1/forecast"
AIR = "https://air-quality-api.open-meteo.com/v1/air-quality"
POLLEN = ("alder_pollen", "birch_pollen", "grass_pollen", "mugwort_pollen", "olive_pollen", "ragweed_pollen")
CURRENT = {
    "temperature_2m": "t",
    "apparent_temperature": "feels",
    "relative_humidity_2m": "h",
    "precipitation": "rain",
    "wind_speed_10m": "wind",
    "wind_gusts_10m": "gust",
    "cloud_cover": "clouds",
    "pressure_msl": "pressure",
    "weather_code": "code",
    "is_day": "day",
}
HOURLY = {
    "temperature_2m": "t",
    "precipitation": "rain",
    "precipitation_probability": "prob",
    "wind_speed_10m": "wind",
    "wind_gusts_10m": "gust",
    "weather_code": "code",
    "is_day": "day",
}
DAILY = {
    "temperature_2m_max": "max",
    "temperature_2m_min": "min",
    "precipitation_sum": "rain",
    "precipitation_probability_max": "prob",
    "wind_gusts_10m_max": "gust",
    "weather_code": "code",
}
CODES = {
    "clear": {"uk": "ясно", "ru": "ясно", "en": "clear"},
    "partly": {"uk": "мінлива хмарність", "ru": "переменная облачность", "en": "partly cloudy"},
    "cloudy": {"uk": "хмарно", "ru": "облачно", "en": "cloudy"},
    "fog": {"uk": "туман", "ru": "туман", "en": "fog"},
    "drizzle": {"uk": "мряка", "ru": "морось", "en": "drizzle"},
    "rain": {"uk": "дощ", "ru": "дождь", "en": "rain"},
    "freezing": {"uk": "крижаний дощ", "ru": "ледяной дождь", "en": "freezing rain"},
    "snow": {"uk": "сніг", "ru": "снег", "en": "snow"},
    "showers": {"uk": "злива", "ru": "ливень", "en": "showers"},
    "storm": {"uk": "гроза", "ru": "гроза", "en": "thunderstorm"},
}


LOOKS = {
    "clear": ("sun", "moon", "amber", "violet"),
    "partly": ("cloud_sun", "cloud_moon", "amber", "violet"),
    "cloudy": ("cloud", "cloud", "", ""),
    "fog": ("fog", "fog", "", ""),
    "drizzle": ("drizzle", "drizzle", "frost", "frost"),
    "rain": ("rain", "rain", "frost", "frost"),
    "freezing": ("rain", "rain", "frost", "frost"),
    "snow": ("snow", "snow", "frost", "frost"),
    "showers": ("rain", "rain", "frost", "frost"),
    "storm": ("storm", "storm", "warn", "warn"),
}


def look(cond: Any, day: Any = 1) -> tuple[str, str]:
    """Значок и цвет для группы погоды, ночью луна вместо солнца."""
    v = LOOKS.get(str(cond or ""))
    if not v:
        return "cloud", ""
    night = day is not None and not day
    return (v[1], v[3]) if night else (v[0], v[2])


def condition(code: Any) -> str:
    """Группа по коду WMO, который возвращает Open-Meteo."""
    if not isinstance(code, (int, float)):
        return ""
    c = int(code)
    if c == 0:
        return "clear"
    if c in (1, 2):
        return "partly"
    if c == 3:
        return "cloudy"
    if c in (45, 48):
        return "fog"
    if c in (56, 57, 66, 67):
        return "freezing"
    if 51 <= c <= 55:
        return "drizzle"
    if 61 <= c <= 65:
        return "rain"
    if 71 <= c <= 77 or c in (85, 86):
        return "snow"
    if 80 <= c <= 82:
        return "showers"
    if c >= 95:
        return "storm"
    return ""


def forecast_url(lat: float, lon: float) -> str:
    q = {
        "latitude": f"{lat:.4f}",
        "longitude": f"{lon:.4f}",
        "current": ",".join(CURRENT),
        "hourly": ",".join(HOURLY),
        "daily": ",".join(DAILY),
        "wind_speed_unit": "ms",
        "timezone": "auto",
        "forecast_days": "4",
    }
    return f"{FORECAST}?{urllib.parse.urlencode(q)}"


GEOCODE = "https://geocoding-api.open-meteo.com/v1/search"
GEOGET = "https://geocoding-api.open-meteo.com/v1/get"
SEARCH_LANGS = ("uk", "ru", "en")
DEMO_PLACES = [
    ("Helsinki", "Хельсинки", "Гельсінкі", "Uusimaa", "FI", 60.1695, 24.9354),
    ("Tampere", "Тампере", "Тампере", "Pirkanmaa", "FI", 61.4991, 23.7871),
    ("Oulu", "Оулу", "Оулу", "North Ostrobothnia", "FI", 65.0124, 25.4682),
    ("Kyiv", "Киев", "Київ", "Kyiv City", "UA", 50.4501, 30.5234),
    ("Lviv", "Львов", "Львів", "Lviv Oblast", "UA", 49.8397, 24.0297),
    ("Irpin", "Ирпень", "Ірпінь", "Kyiv Oblast", "UA", 50.5218, 30.2506),
    ("Odesa", "Одесса", "Одеса", "Odesa Oblast", "UA", 46.4825, 30.7233),
    ("Berlin", "Берлин", "Берлін", "Berlin", "DE", 52.52, 13.405),
]


def geocode_url(q: str, lang: str, count: int = 8) -> str:
    return f"{GEOCODE}?{urllib.parse.urlencode({'name': q, 'count': count, 'language': lang, 'format': 'json'})}"


def search_langs(lang: str) -> list[str]:
    """Язык интерфейса первым, затем украинский, русский и английский, геокодер ищет по названиям на языке запроса."""
    return list(dict.fromkeys([lang, *SEARCH_LANGS]))


def place_url(pid: int, lang: str) -> str:
    return f"{GEOGET}?{urllib.parse.urlencode({'id': pid, 'language': lang})}"


def merge_places(groups: list[list[dict[str, Any]]], count: int = 8) -> list[dict[str, Any]]:
    seen: set[Any] = set()
    out = []
    for group in groups:
        for p in group:
            key = p.get("id") or (round(p["lat"], 2), round(p["lon"], 2))
            if key in seen:
                continue
            seen.add(key)
            out.append(p)
    return out[:count]


def parse_places(js: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for r in js.get("results") or []:
        lat, lon = r.get("latitude"), r.get("longitude")
        ok = all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in (lat, lon))
        if not ok or not r.get("name"):
            continue
        pid = r.get("id")
        out.append(
            {
                "id": pid if isinstance(pid, int) and not isinstance(pid, bool) else None,
                "name": str(r["name"])[:80],
                "admin": str(r.get("admin1") or "")[:80],
                "country": str(r.get("country_code") or r.get("country") or "")[:40],
                "lat": round(lat, 4),
                "lon": round(lon, 4),
            }
        )
    return out


def demo_places(q: str, lang: str) -> list[dict[str, Any]]:
    q = q.strip().lower()
    idx = {"ru": 1, "uk": 2}.get(lang, 0)
    return [
        {"name": p[idx], "admin": p[3], "country": p[4], "lat": p[5], "lon": p[6]}
        for p in DEMO_PLACES
        if q and any(q in n.lower() for n in p[:3])
    ]


def air_url(lat: float, lon: float) -> str:
    q = {
        "latitude": f"{lat:.4f}",
        "longitude": f"{lon:.4f}",
        "current": ",".join(("european_aqi", "pm2_5", "pm10", *POLLEN)),
        "hourly": ",".join(("european_aqi", *POLLEN)),
        "timezone": "auto",
        "forecast_days": "2",
    }
    return f"{AIR}?{urllib.parse.urlencode(q)}"


def _num(v: Any) -> float | None:
    return round(float(v), 1) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _tz(js: dict[str, Any]) -> timezone:
    return timezone(timedelta(seconds=int(js.get("utc_offset_seconds") or 0)))


def _ts(s: str, tz: timezone) -> str:
    return datetime.fromisoformat(s).replace(tzinfo=tz).astimezone(UTC).isoformat()


def _rows(block: dict[str, Any], names: dict[str, str], tz: timezone, stamp: bool = True) -> list[dict[str, Any]]:
    times = block.get("time") or []
    out = []
    for i, t in enumerate(times):
        row: dict[str, Any] = {"ts": _ts(t, tz) if stamp else t}
        for src, dst in names.items():
            vals = block.get(src) or []
            row[dst] = _num(vals[i]) if i < len(vals) else None
        out.append(row)
    return out


def parse_forecast(js: dict[str, Any]) -> dict[str, Any]:
    tz = _tz(js)
    cur = js.get("current") or {}
    current = {dst: _num(cur.get(src)) for src, dst in CURRENT.items()}
    current["cond"] = condition(current.get("code"))
    hourly = _rows(js.get("hourly") or {}, HOURLY, tz)
    daily = _rows(js.get("daily") or {}, DAILY, tz, stamp=False)
    for r in hourly + daily:
        r["cond"] = condition(r.get("code"))
    return {"current": current, "hourly": hourly, "daily": daily}


def pollen_max(src: dict[str, Any]) -> tuple[float | None, str]:
    best, name = None, ""
    for k in POLLEN:
        v = _num(src.get(k))
        if v is not None and (best is None or v > best):
            best, name = v, k.removesuffix("_pollen")
    return best, name


def parse_air(js: dict[str, Any]) -> dict[str, Any]:
    tz = _tz(js)
    cur = js.get("current") or {}
    pollen, kind = pollen_max(cur)
    current = {
        "aqi": _num(cur.get("european_aqi")),
        "pm25": _num(cur.get("pm2_5")),
        "pm10": _num(cur.get("pm10")),
        "pollen": pollen,
        "pollen_kind": kind,
    }
    hb = js.get("hourly") or {}
    hourly = []
    for i, t in enumerate(hb.get("time") or []):
        aqi = hb.get("european_aqi") or []
        p, _ = pollen_max({k: hb[k][i] for k in POLLEN if i < len(hb.get(k) or [])})
        hourly.append({"ts": _ts(t, tz), "aqi": _num(aqi[i]) if i < len(aqi) else None, "pollen": p})
    return {"current": current, "hourly": hourly}


def window(rows: list[dict[str, Any]], hours: float, now: datetime) -> list[dict[str, Any]]:
    start = now.replace(minute=0, second=0, microsecond=0)
    end = now + timedelta(hours=hours)
    return [r for r in rows if start <= datetime.fromisoformat(r["ts"]) <= end]


def rain_expected(rows: list[dict[str, Any]], prob: float, min_mm: float = 0.1) -> tuple[bool, float]:
    total = round(sum(r.get("rain") or 0 for r in rows), 1)
    wet = [
        r for r in rows if (r.get("rain") or 0) >= min_mm and (r.get("prob") is None or (r.get("prob") or 0) >= prob)
    ]
    return bool(wet), total


def extreme(rows: list[dict[str, Any]], key: str, low: bool) -> float | None:
    vals = [r[key] for r in rows if r.get(key) is not None]
    if not vals:
        return None
    return min(vals) if low else max(vals)


def demo(now: datetime, shift: float = 0.0) -> tuple[dict[str, Any], dict[str, Any]]:
    base = now.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
    hourly = []
    for i in range(-2, 72):
        ts = base + timedelta(hours=i)
        local_h = (ts.hour + 2) % 24
        day = 1.0 if 8 <= local_h < 16 else 0.0
        t = round(3.0 + shift + 3.0 * math.sin((local_h - 9) / 24 * 2 * math.pi) - i * 0.05, 1)
        wet = 10 <= i <= 14
        hourly.append(
            {
                "ts": ts.isoformat(),
                "t": t,
                "rain": 0.6 if wet else 0.0,
                "prob": 80.0 if wet else 10.0,
                "wind": 4.0 + (i % 5),
                "gust": 8.0 + (i % 7),
                "code": 61.0 if wet else 2.0,
                "cond": "rain" if wet else "partly",
                "day": day,
            }
        )
    cur = hourly[2]
    current = {
        "t": cur["t"],
        "feels": round(cur["t"] - 2.5, 1),
        "h": 84.0,
        "rain": cur["rain"],
        "wind": cur["wind"],
        "gust": cur["gust"],
        "clouds": 60.0,
        "pressure": 1012.0,
        "code": cur["code"],
        "cond": cur["cond"],
        "day": cur["day"],
    }
    daily = []
    for d in range(4):
        day = hourly[2 + d * 24 : 2 + (d + 1) * 24] or hourly[-24:]
        daily.append(
            {
                "ts": (base + timedelta(days=d)).date().isoformat(),
                "max": max(r["t"] for r in day),
                "min": min(r["t"] for r in day),
                "rain": round(sum(r["rain"] for r in day), 1),
                "prob": max(r["prob"] for r in day),
                "gust": max(r["gust"] for r in day),
                "code": 61.0 if d == 0 else 3.0,
                "cond": "rain" if d == 0 else "cloudy",
            }
        )
    air_hourly = [{"ts": r["ts"], "aqi": 22.0 + (i % 6), "pollen": 0.0} for i, r in enumerate(hourly[:50])]
    air = {"current": {"aqi": 24.0, "pm25": 3.1, "pm10": 6.4, "pollen": 0.0, "pollen_kind": ""}, "hourly": air_hourly}
    return {"current": current, "hourly": hourly, "daily": daily}, air
