import asyncio
import json
import math
import time
import urllib.request
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

import omlogic as om
from valo_sdk import Extension

ext = Extension()
FORECAST_EVERY = 1800
AIR_EVERY = 3600
WEEKDAYS = {
    "uk": ["пн", "вт", "ср", "чт", "пт", "сб", "нд"],
    "ru": ["пн", "вт", "ср", "чт", "пт", "сб", "вс"],
    "en": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
    "de": ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"],
    "es": ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"],
    "fr": ["lun", "mar", "mer", "jeu", "ven", "sam", "dim"],
    "ja": ["月", "火", "水", "木", "金", "土", "日"],
}
ext.device(
    "weather",
    {
        "uk": "Погода Open-Meteo",
        "ru": "Погода Open-Meteo",
        "en": "Open-Meteo weather",
        "de": "Open-Meteo Wetter",
        "es": "Tiempo Open-Meteo",
        "fr": "Météo Open-Meteo",
        "ja": "Open-Meteo 天気",
    },
    [
        {"id": "t", "type": "num", "unit": "°C", "access": "r"},
        {"id": "feels", "type": "num", "unit": "°C", "access": "r"},
        {"id": "h", "type": "num", "unit": "%", "access": "r"},
        {"id": "rain", "type": "num", "unit": "mm", "access": "r"},
        {"id": "wind", "type": "num", "unit": "m/s", "access": "r"},
        {"id": "gust", "type": "num", "unit": "m/s", "access": "r"},
        {"id": "clouds", "type": "num", "unit": "%", "access": "r"},
        {"id": "pressure", "type": "num", "unit": "hPa", "access": "r"},
        {"id": "cond", "type": "enum", "access": "r", "values": list(om.CODES)},
    ],
    kind="weather",
    model="Open-Meteo",
)
AIR_ON = str(ext.settings.get("air") or "on") == "on"
if AIR_ON:
    ext.device(
        "air",
        {
            "uk": "Якість повітря Open-Meteo",
            "ru": "Качество воздуха Open-Meteo",
            "en": "Open-Meteo air quality",
            "de": "Open-Meteo Luftqualität",
            "es": "Calidad del aire Open-Meteo",
            "fr": "Qualité de l'air Open-Meteo",
            "ja": "Open-Meteo 大気質",
        },
        [
            {"id": "aqi", "type": "num", "unit": "EAQI", "access": "r"},
            {"id": "pm25", "type": "num", "unit": "µg/m³", "access": "r"},
            {"id": "pm10", "type": "num", "unit": "µg/m³", "access": "r"},
            {"id": "pollen", "type": "num", "unit": "grains/m³", "access": "r"},
        ],
        kind="air",
        model="Open-Meteo",
    )
data: dict[str, Any] = {"fc": {"current": {}, "hourly": [], "daily": []}, "air": {"current": {}, "hourly": []}}
meta: dict[str, Any] = {"tz": ZoneInfo("Europe/Helsinki"), "lat": None, "lon": None, "fc_at": 0.0, "air_at": 0.0}


def get_json(url: str) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": "Valo smart home"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def demo_mode() -> bool:
    return ext.demo or ext.settings.get("source") == "demo"


def coord(key: str) -> float | None:
    v = str(ext.settings.get(key) or "").strip().replace(",", ".")
    if not v:
        return None
    try:
        x = float(v)
    except ValueError:
        x = math.nan
    if not math.isfinite(x) or abs(x) > (90 if key == "lat" else 180):
        ext.log.warning("setting %s is not a valid coordinate, home location is used", key)
        return None
    return x


@ext.on_start
async def start() -> None:
    try:
        home = await ext.call("home")
        meta["tz"] = ZoneInfo(home.get("timezone") or "Europe/Helsinki")
        meta["lat"], meta["lon"] = home.get("lat"), home.get("lon")
    except Exception as e:
        ext.log.warning("home info unavailable: %s", e)
    lat, lon = coord("lat"), coord("lon")
    if lat is not None and lon is not None:
        meta["lat"], meta["lon"] = lat, lon


async def refresh() -> None:
    now = time.time()
    if demo_mode():
        data["fc"], data["air"] = om.demo(datetime.now(UTC))
        meta["fc_at"] = meta["air_at"] = now
    else:
        lat, lon = meta["lat"], meta["lon"]
        if lat is None or lon is None:
            ext.log.error("location unknown: set home coordinates or lat and lon in settings")
            return
        if now - meta["fc_at"] >= FORECAST_EVERY:
            data["fc"] = om.parse_forecast(await asyncio.to_thread(get_json, om.forecast_url(lat, lon)))
            meta["fc_at"] = now
            ext.log.info("forecast %s hours, %s days", len(data["fc"]["hourly"]), len(data["fc"]["daily"]))
        if AIR_ON and now - meta["air_at"] >= AIR_EVERY:
            data["air"] = om.parse_air(await asyncio.to_thread(get_json, om.air_url(lat, lon)))
            meta["air_at"] = now
    cur = data["fc"]["current"]
    if meta["fc_at"] == now or meta["air_at"] == now:
        await ext.changed("weather", "now")
    if cur:
        rows = om.window(data["fc"]["hourly"], 24, datetime.now(UTC))
        await ext.state(
            "weather",
            {k: cur.get(k) for k in ("t", "feels", "h", "rain", "wind", "gust", "clouds", "pressure", "cond")}
            | {"_attrs": {"forecast": rows, "daily": data["fc"]["daily"]}},
        )
    if AIR_ON and data["air"]["current"]:
        a = data["air"]["current"]
        await ext.state(
            "air", {k: a.get(k) for k in ("aqi", "pm25", "pm10", "pollen")} | {"_attrs": {"kind": a.get("pollen_kind")}}
        )


@ext.loop
async def loop() -> None:
    while True:
        try:
            await refresh()
        except Exception as e:
            ext.log.error("open-meteo refresh failed: %s", e)
        await asyncio.sleep(300)


def hours_ahead(params: dict, default: float) -> list[dict[str, Any]]:
    return om.window(data["fc"]["hourly"], float(params.get("hours") or default), datetime.now(UTC))


def answer(ok: bool, value: Any, target: Any, key: str) -> dict[str, Any]:
    out = [0, {key: value}] if ok else [1]
    return {
        "outs": [out],
        "trace": {"s": "ok" if ok else "no", "m": "ext_value", "p": {"value": value, "target": target}},
    }


@ext.block("rain_expected")
async def rain_expected(params: dict, token: dict, dry: bool) -> dict:
    prob = float(params.get("prob") if params.get("prob") is not None else 50)
    ok, total = om.rain_expected(hours_ahead(params, 3), prob)
    return answer(ok, total, prob, "mm")


@ext.block("frost_expected")
async def frost_expected(params: dict, token: dict, dry: bool) -> dict:
    limit = float(params.get("value") or 0)
    low = om.extreme(hours_ahead(params, 12), "t", low=True)
    return answer(low is not None and low <= limit, low, limit, "min")


@ext.block("heat_expected")
async def heat_expected(params: dict, token: dict, dry: bool) -> dict:
    limit = float(params.get("value") if params.get("value") is not None else 27)
    high = om.extreme(hours_ahead(params, 24), "t", low=False)
    return answer(high is not None and high >= limit, high, limit, "max")


@ext.block("wind_above")
async def wind_above(params: dict, token: dict, dry: bool) -> dict:
    limit = float(params.get("value") if params.get("value") is not None else 15)
    gust = om.extreme(hours_ahead(params, 6), "gust", low=False)
    return answer(gust is not None and gust >= limit, gust, limit, "gust")


@ext.block("air_bad")
async def air_bad(params: dict, token: dict, dry: bool) -> dict:
    limit = float(params.get("value") if params.get("value") is not None else 60)
    aqi = data["air"]["current"].get("aqi")
    return answer(aqi is not None and aqi >= limit, aqi, limit, "aqi")


@ext.block("pollen_high")
async def pollen_high(params: dict, token: dict, dry: bool) -> dict:
    limit = float(params.get("value") if params.get("value") is not None else 50)
    p = data["air"]["current"].get("pollen")
    return answer(p is not None and p >= limit, p, limit, "pollen")


def L(uk: str, ru: str, en: str) -> dict[str, str]:
    return {"uk": uk, "ru": ru, "en": en}


def stat(label: dict[str, str], value: Any, unit: str, digits: int = 1) -> dict[str, Any]:
    return {"label": label, "value": value, "unit": unit, "digits": digits}


def cond_text(cond: str, lang: str) -> str:
    names = om.CODES.get(cond) or {}
    return names.get(lang) or names.get("en") or "-"


def local(ts: str) -> datetime:
    return datetime.fromisoformat(ts).astimezone(meta["tz"])


def place(comma: bool) -> str:
    lat, lon = meta["lat"], meta["lon"]
    if lat is None or lon is None:
        return "-"
    a, b = str(round(float(lat), 4)), str(round(float(lon), 4))
    return f"{a}; {b}".replace(".", ",") if comma else f"{a}, {b}"


def hero(lang: str, fc: dict[str, Any], full: bool = False) -> dict[str, Any]:
    cur = fc["current"]
    icon, tone = om.look(cur.get("cond"), cur.get("day"))
    sub: list[dict[str, Any]] = [
        {"label": L("Відчувається", "Ощущается", "Feels like"), "value": cur.get("feels"), "unit": "°", "digits": 0}
    ]
    today = (fc.get("daily") or [{}])[0]
    if today.get("min") is not None and today.get("max") is not None:
        sub.append({"label": L("мін", "мин", "min"), "value": today["min"], "unit": "°", "digits": 0})
        sub.append({"label": L("макс", "макс", "max"), "value": today["max"], "unit": "°", "digits": 0})
    items = [
        {"icon": "wind", "label": L("Вітер", "Ветер", "Wind"), "value": cur.get("wind"), "unit": "m/s", "digits": 0},
        {
            "icon": "drop",
            "label": L("Вологість", "Влажность", "Humidity"),
            "value": cur.get("h"),
            "unit": "%",
            "digits": 0,
        },
    ]
    if full:
        items += [
            {
                "icon": "wind",
                "label": L("Пориви", "Порывы", "Gusts"),
                "value": cur.get("gust"),
                "unit": "m/s",
                "digits": 0,
            },
            {
                "icon": "cloud",
                "label": L("Хмарність", "Облачность", "Cloud cover"),
                "value": cur.get("clouds"),
                "unit": "%",
                "digits": 0,
            },
            {
                "icon": "chart",
                "label": L("Тиск", "Давление", "Pressure"),
                "value": cur.get("pressure"),
                "unit": "hPa",
                "digits": 0,
            },
        ]
    return {
        "type": "hero",
        "icon": icon,
        "tone": tone,
        "value": cur.get("t"),
        "unit": "°C",
        "digits": 1,
        "text": cond_text(str(cur.get("cond") or ""), lang),
        "sub": sub,
        "items": items,
    }


def hours_strip(fc: dict[str, Any], step: int = 3, count: int = 8) -> dict[str, Any]:
    rows = om.window(fc["hourly"], step * count, datetime.now(UTC))
    cur = fc["current"]
    items = []
    for i, r in enumerate(rows[: step * count : step]):
        icon, tone = om.look(cur.get("cond") if i == 0 else r.get("cond"), cur.get("day") if i == 0 else r.get("day"))
        prob = r.get("prob")
        items.append(
            {
                "label": L("Зараз", "Сейчас", "Now") if i == 0 else local(r["ts"]).strftime("%H:%M"),
                "icon": icon,
                "tone": tone,
                "value": cur.get("t") if i == 0 and cur.get("t") is not None else r.get("t"),
                "unit": "°",
                "digits": 0,
                "sub": f"{prob:.0f}%" if isinstance(prob, (int, float)) and prob >= 30 else "",
            }
        )
    return {"type": "strip", "label": L("Найближчі години", "Ближайшие часы", "Next hours"), "now": 0, "items": items}


def temp_bars(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "type": "bars",
        "label": L("Температура на 24 години, °C", "Температура на 24 часа, °C", "Temperature for 24 hours, °C"),
        "values": [r.get("t") for r in rows],
        "labels": [local(r["ts"]).strftime("%H:%M") for r in rows],
        "now": 0,
        "unit": "°C",
        "digits": 1,
        "series": [
            {"label": L("Вище нуля", "Выше нуля", "Above zero"), "color": "amber"},
            {"label": L("Нуль і нижче", "Ноль и ниже", "Zero and below"), "color": "frost"},
        ],
        "kinds": [1 if (r.get("t") or 0) <= 0 else 0 for r in rows],
    }


@ext.page("weather")
async def page_weather(params: dict) -> dict:
    lang = str(params.get("lang") or "uk")
    if not data["fc"]["current"]:
        return {
            "blocks": [
                {"type": "text", "text": L("Прогноз ще не отримано", "Прогноз еще не получен", "No forecast yet")}
            ]
        }
    rows = om.window(data["fc"]["hourly"], 24, datetime.now(UTC))
    wet = [r for r in rows if r.get("prob") is not None]
    blocks: list[dict[str, Any]] = [hero(lang, data["fc"], full=True), hours_strip(data["fc"]), temp_bars(rows)]
    if wet:
        marks = [i for i, r in enumerate(wet) if (r.get("rain") or 0) >= 0.1]
        blocks.append(
            {
                "type": "bars",
                "label": L("Імовірність опадів, %", "Вероятность осадков, %", "Chance of precipitation, %"),
                "values": [r.get("prob") for r in wet],
                "labels": [local(r["ts"]).strftime("%H:%M") for r in wet],
                "now": 0,
                "marks": marks,
                "unit": "%",
                "digits": 0,
                "series": [
                    {"label": L("Без опадів", "Без осадков", "No precipitation"), "color": "ink"},
                    {"label": L("Очікуються опади", "Ожидаются осадки", "Precipitation expected"), "color": "frost"},
                ],
                "kinds": [1 if i in marks else 0 for i in range(len(wet))],
            }
        )
    days = []
    for d in data["fc"]["daily"]:
        wd = datetime.fromisoformat(d["ts"]).weekday()
        name = f"{WEEKDAYS.get(lang, WEEKDAYS['en'])[wd]} {d['ts'][8:10]}.{d['ts'][5:7]}"
        values: list[Any] = []
        if d.get("min") is not None and d.get("max") is not None:
            values.append({"range": [d["min"], d["max"]], "unit": "°C", "digits": 1})
        values.append(om.CODES.get(str(d.get("cond") or "")) or "-")
        values.append({"value": d.get("rain") or 0, "unit": "mm", "digits": 1})
        days.append({"text": name, "values": values})
    blocks.append({"type": "list", "label": L("Прогноз на дні", "Прогноз по дням", "Daily forecast"), "items": days})
    if AIR_ON and data["air"]["current"]:
        a = data["air"]["current"]
        blocks.append(
            {
                "type": "stats",
                "items": [
                    stat(L("Якість повітря", "Качество воздуха", "Air quality"), a.get("aqi"), "EAQI", 0),
                    stat(L("PM2.5", "PM2.5", "PM2.5"), a.get("pm25"), "µg/m³"),
                    stat(L("PM10", "PM10", "PM10"), a.get("pm10"), "µg/m³"),
                    stat(L("Пилок", "Пыльца", "Pollen"), a.get("pollen"), "grains/m³", 0),
                ],
            }
        )
    if demo_mode():
        src = L("Дані Open-Meteo, демо", "Данные Open-Meteo, демо", "Open-Meteo data, demo")
    else:
        src = L(
            f"Дані Open-Meteo, {place(True)}", f"Данные Open-Meteo, {place(True)}", f"Open-Meteo data, {place(False)}"
        )
    blocks.append({"type": "text", "text": src})
    return {"blocks": blocks, "updated": datetime.fromtimestamp(meta["fc_at"], UTC).isoformat()}


places: dict[str, dict[str, Any]] = {}


def place_of(params: dict) -> tuple[float, float, str] | None:
    p = params.get("place")
    if not isinstance(p, dict):
        return None
    try:
        lat, lon = float(p["lat"]), float(p["lon"])
    except KeyError, TypeError, ValueError:
        return None
    if not (math.isfinite(lat) and math.isfinite(lon) and abs(lat) <= 90 and abs(lon) <= 180):
        return None
    return lat, lon, str(p.get("name") or "")[:80]


async def forecast_for(lat: float, lon: float) -> dict[str, Any]:
    key = f"{lat:.2f},{lon:.2f}"
    hit = places.get(key)
    if hit and time.time() - hit["at"] < FORECAST_EVERY:
        return hit["fc"]
    if demo_mode():
        fc, _ = om.demo(datetime.now(UTC), shift=round((60.17 - lat) / 2, 1))
    else:
        fc = om.parse_forecast(await asyncio.to_thread(get_json, om.forecast_url(lat, lon)))
        ext.log.info("forecast for %s loaded", key)
    if len(places) >= 50:
        places.clear()
    places[key] = {"fc": fc, "at": time.time()}
    return fc


@ext.page("geocode")
async def page_geocode(params: dict) -> dict:
    q, lang = str(params.get("q") or "").strip()[:80], str(params.get("lang") or "uk")
    if len(q) < 2:
        return {"places": []}
    if demo_mode():
        return {"places": om.demo_places(q, lang)}
    langs = om.search_langs(lang)
    found = await asyncio.gather(
        *(asyncio.to_thread(get_json, om.geocode_url(q, x)) for x in langs), return_exceptions=True
    )
    groups, errors = [], []
    for x, js in zip(langs, found, strict=True):
        if isinstance(js, BaseException):
            errors.append(f"{x}: {js}")
            continue
        groups.append([p | {"lang": x} for p in om.parse_places(js)])
    if errors:
        ext.log.warning("geocoding for %r failed in %s", q, "; ".join(errors)[:300])
    if not groups:
        return {"places": [], "error": errors[0][:200]}
    merged = om.merge_places(groups)
    foreign = [p for p in merged if p["lang"] != lang and p.get("id")]
    if foreign:
        named = await asyncio.gather(
            *(asyncio.to_thread(get_json, om.place_url(p["id"], lang)) for p in foreign), return_exceptions=True
        )
        for p, js in zip(foreign, named, strict=True):
            loc = om.parse_places({"results": [js]}) if isinstance(js, dict) else []
            if loc:
                p.update(name=loc[0]["name"], admin=loc[0]["admin"] or p["admin"])
            elif isinstance(js, BaseException):
                ext.log.warning("place %s name in %s failed: %s", p["id"], lang, js)
    return {"places": [{k: v for k, v in p.items() if k != "lang"} for p in merged]}


@ext.page("now")
async def page_now(params: dict) -> dict:
    lang = str(params.get("lang") or "uk")
    where = place_of(params)
    fc = data["fc"]
    if where:
        try:
            fc = await forecast_for(where[0], where[1])
        except Exception as e:
            ext.log.warning("forecast for %s failed: %s", where[2] or where[:2], e)
            return {
                "blocks": [
                    {"type": "text", "text": L("Прогноз недоступний", "Прогноз недоступен", "Forecast unavailable")}
                ]
            }
    if not fc["current"]:
        return {
            "blocks": [
                {"type": "text", "text": L("Прогноз ще не отримано", "Прогноз еще не получен", "No forecast yet")}
            ]
        }
    return {"blocks": [hero(lang, fc), hours_strip(fc)]}


if __name__ == "__main__":
    ext.run()
