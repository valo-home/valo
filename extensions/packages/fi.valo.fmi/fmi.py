import asyncio
import math
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import UTC, datetime, timedelta

from valo_sdk import Extension

ext = Extension()
URL = "https://opendata.fmi.fi/wfs?service=WFS&version=2.0.0&request=getFeature&storedquery_id=fmi::forecast::harmonie::surface::point::simple&place={p}&parameters=temperature,humidity,windspeedms,precipitation1h&timestep=60"
NS = {"wfs": "http://www.opengis.net/wfs/2.0", "BsWfs": "http://xml.fmi.fi/schema/wfs/2.0"}
ext.device(
    "weather",
    "FMI",
    [
        {"id": "t", "type": "num", "unit": "°C", "access": "r"},
        {"id": "h", "type": "num", "unit": "%", "access": "r"},
        {"id": "wind", "type": "num", "unit": "m/s", "access": "r"},
        {"id": "rain", "type": "num", "unit": "mm", "access": "r"},
    ],
    kind="weather",
)
forecast: list[dict] = []


def fetch(place: str) -> list[dict]:
    with urllib.request.urlopen(URL.format(p=urllib.parse.quote(place)), timeout=20) as r:
        root = ET.fromstring(r.read())
    rows: dict[str, dict] = {}
    for el in root.iter("{http://xml.fmi.fi/schema/wfs/2.0}BsWfsElement"):
        t = el.findtext("BsWfs:Time", namespaces=NS)
        name = el.findtext("BsWfs:ParameterName", namespaces=NS)
        val = el.findtext("BsWfs:ParameterValue", namespaces=NS)
        key = {"temperature": "t", "humidity": "h", "windspeedms": "wind", "precipitation1h": "rain"}.get(name or "")
        if t and key and val not in (None, "NaN"):
            rows.setdefault(t, {"ts": t})[key] = round(float(val), 1)
    return [rows[k] for k in sorted(rows)]


def demo() -> list[dict]:
    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    out = []
    for i in range(48):
        ts = now + timedelta(hours=i)
        h = (ts.hour + 2) % 24
        out.append(
            {
                "ts": ts.isoformat(),
                "t": round(3.5 + 2.5 * math.sin((h - 9) / 24 * 2 * math.pi), 1),
                "h": 82,
                "wind": 4.2,
                "rain": 0.4 if 14 <= i <= 18 else 0.0,
            }
        )
    return out


@ext.loop
async def refresh() -> None:
    while True:
        try:
            use_demo = ext.demo or ext.settings.get("source") == "demo"
            rows = demo() if use_demo else await asyncio.to_thread(fetch, str(ext.settings.get("place") or "Espoo"))
            if rows:
                forecast[:] = rows
                await ext.state(
                    "weather",
                    {k: rows[0].get(k) for k in ("t", "h", "wind", "rain")} | {"_attrs": {"forecast": rows[:24]}},
                )
        except Exception as e:
            ext.log.warning("forecast failed: %s", e)
        await asyncio.sleep(1800)


def window(hours: float) -> list[dict]:
    end = datetime.now(UTC) + timedelta(hours=hours)
    return [r for r in forecast if datetime.fromisoformat(r["ts"].replace("Z", "+00:00")) <= end]


@ext.block("rain_expected")
async def rain(params: dict, token: dict, dry: bool) -> dict:
    total = round(sum(r.get("rain") or 0 for r in window(float(params.get("hours") or 3))), 1)
    ok = total >= 0.2
    return {
        "outs": [[0 if ok else 1]],
        "trace": {"s": "ok" if ok else "no", "m": "ext_value", "p": {"value": total, "target": 0.2}},
    }


@ext.block("frost_expected")
async def frost(params: dict, token: dict, dry: bool) -> dict:
    low = min((r.get("t") for r in window(float(params.get("hours") or 12)) if r.get("t") is not None), default=None)
    ok = low is not None and low <= 0
    return {
        "outs": [[0 if ok else 1]],
        "trace": {"s": "ok" if ok else "no", "m": "ext_value", "p": {"value": low, "target": 0}},
    }


if __name__ == "__main__":
    ext.run()
