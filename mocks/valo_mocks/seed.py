import asyncio
import logging
import math
import os
import random
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx

log = logging.getLogger("mocks.seed")
API = os.environ.get("VALO_API", "http://localhost:8000/api/v1")


class Api:
    def __init__(self) -> None:
        self.c = httpx.AsyncClient(base_url=API, timeout=30)

    async def __call__(self, method: str, path: str, body: Any = None) -> Any:
        r = await self.c.request(method, path, json=body)
        if r.status_code >= 400:
            raise RuntimeError(f"{method} {path} {r.status_code} {r.text[:300]}")
        return r.json() if r.content else None


def refs(obj: Any, ids: dict[str, str]) -> Any:
    if isinstance(obj, str) and obj.startswith("@"):
        return ids[obj[1:]]
    if isinstance(obj, dict):
        return {refs(k, ids): refs(v, ids) for k, v in obj.items()}
    if isinstance(obj, list):
        return [refs(x, ids) for x in obj]
    return obj


async def until(check: Any, tries: int, label: str) -> Any:
    for i in range(tries):
        try:
            res = await check()
            if res:
                return res
        except (httpx.HTTPError, RuntimeError) as e:
            if i % 10 == 0:
                log.info("waiting for %s: %s", label, e)
        await asyncio.sleep(2)
    raise RuntimeError(f"timeout waiting for {label}")


async def cameras(api: Api, sc: dict[str, Any]) -> None:
    sim = "dev.local.simulator"
    cur = {x["id"]: x for x in await api("GET", "/extensions")}
    if sim not in cur:
        return
    if cur[sim].get("newPerms") or cur[sim].get("update"):
        cat = {e["id"]: e["manifest"] for e in await api("GET", "/extensions/catalog")}
        await api("POST", f"/extensions/{sim}/update", {"grants": cat[sim].get("perms", [])})

    async def driver() -> bool:
        if not any(d["id"] == sim and d["status"] == "running" for d in await api("GET", "/cameras/drivers")):
            raise RuntimeError("camera driver not running")
        return True

    await until(driver, 45, "camera driver")
    have = {c["name"] for c in await api("GET", "/cameras")}
    for c in sc.get("cameras", []):
        if c["name"] not in have:
            await api(
                "POST",
                "/cameras",
                {"driver": sim, "name": c["name"], "roomId": c["room"], "config": {"pattern": c["pattern"]}},
            )
            log.info("demo camera %s added", c["name"])


async def run(sc: dict[str, Any]) -> None:
    api = Api()
    st = await until(lambda: api("GET", "/setup"), 150, "api")
    o, hm = sc["owner"], sc["home"]
    home = {k: hm[k] for k in ("name", "lat", "lon", "timezone", "currency")}
    if st["done"]:
        s = await api("POST", "/auth/login", {"username": o["username"], "password": o["password"]})
    else:
        s = await api("POST", "/setup", {"owner": {**o, "role": "owner"}, "home": {**home, "settings": hm["settings"]}})
        log.info("setup done, owner %s", o["username"])
    api.c.headers["Authorization"] = f"Bearer {s['token']}"
    ai = await api("GET", "/ai/settings")
    if not ai.get("keySet"):
        url = os.environ.get("MOCKS_LLM_URL", "http://mocks:8090/v1")
        await api("PATCH", "/ai/settings", {"enabled": True, "baseUrl": url, "model": "valo/demo", "apiKey": "demo"})
        log.info("demo assistant model at %s", url)
    if (await api("GET", "/home"))["settings"].get("demoSeeded"):
        await cameras(api, sc)
        log.info("demo already seeded")
        return
    have = {r["id"] for r in await api("GET", "/rooms")}
    for i, r in enumerate(sc["rooms"], 1):
        if r["id"] not in have:
            await api("POST", "/rooms", {**r, "sort": i})
    have = {u["username"] for u in await api("GET", "/users")}
    for u in sc["users"]:
        if u["username"] not in have:
            await api("POST", "/users", u)
    ha = {x["key"]: x["id"] for x in sc["ha"]}
    ids = (
        {d["key"]: d["ieee"] for d in sc["zigbee"]}
        | {h["key"]: h["key"] for h in sc["hub"]}
        | ha
        | {m["id"]: m["id"] for m in sc["mapping"]}
    )
    want = set(ids.values()) - {m["id"] for m in sc["mapping"]}

    async def devices() -> dict[str, Any] | None:
        got = {d["id"]: d for d in await api("GET", "/devices")}
        if want <= set(got):
            return got
        raise RuntimeError(f"{len(want & set(got))} of {len(want)} devices")

    got = await until(devices, 120, "devices")
    for d in [*sc["zigbee"], *sc["hub"], *sc["ha"]]:
        cur = got[ids[d["key"]]]
        body = {
            k: v
            for k, v in (("name", d["name"]), ("roomId", d["room"]), ("kind", sc["kinds"].get(d["key"])))
            if v and cur.get(k) != v
        }
        if body:
            await api("PATCH", f"/devices/{cur['id']}", body)
    for m in sc["mapping"]:
        if m["id"] not in got:
            await api("POST", "/devices/mapping", m)
    log.info("devices ready, %s", len(got))
    have = {x["id"] for x in await api("GET", "/scenes")}
    for i, x in enumerate(sc["scenes"]):
        if x["id"] not in have:
            await api("POST", "/scenes", refs({**x, "sort": i}, ids))
    cat = {e["id"]: e["manifest"] for e in await api("GET", "/extensions/catalog")}
    have = {x["id"] for x in await api("GET", "/extensions")}
    for e in sc["extensions"]:
        if e["id"] not in have:
            await api(
                "POST",
                f"/extensions/{e['id']}/install",
                {"grants": cat[e["id"]].get("perms", []), "version": e.get("version")},
            )

    async def settled() -> bool:
        cur = {x["id"]: x["status"] for x in await api("GET", "/extensions")}
        busy = [k for k in (e["id"] for e in sc["extensions"]) if cur.get(k) in (None, "installing", "starting")]
        if busy:
            raise RuntimeError(f"installing {', '.join(busy)}")
        return True

    await until(settled, 45, "extensions")
    for e in sc["extensions"]:
        if e.get("settings"):
            await api("PATCH", f"/extensions/{e['id']}/settings", {"values": e["settings"]})
    await asyncio.sleep(3)
    await cameras(api, sc)
    have = {f["id"] for f in await api("GET", "/flows")}
    for f in sc["flows"]:
        if f["id"] not in have:
            await api("POST", "/flows", refs(f, ids))
    have = {x["id"] for x in await api("GET", "/dashboards")}
    for x in sc["dashboards"]:
        if x["id"] not in have:
            await api("POST", "/dashboards", refs(x, ids))
    have = {t["name"] for t in await api("GET", "/tokens")}
    for t in sc["tokens"]:
        if t["name"] not in have:
            await api("POST", "/tokens", t)
    if os.environ.get("DATABASE_URL"):
        try:
            await history(await api("GET", "/devices"), sc)
        except Exception:
            log.exception("history backfill failed")
    await api("PATCH", "/home", {"settings": {"demoSeeded": True}})
    log.info(
        "demo seeded: %s rooms, %s scenes, %s flows, %s dashboards",
        len(sc["rooms"]),
        len(sc["scenes"]),
        len(sc["flows"]),
        len(sc["dashboards"]),
    )


def value(
    cap: str, cur: float, d: dict[str, Any], ts: datetime, now: datetime, tz: ZoneInfo, out: bool, rnd: random.Random
) -> float:
    lt, ln, k = ts.astimezone(tz), now.astimezone(tz), d["kind"]
    h, hn = lt.hour + lt.minute / 60, ln.hour + ln.minute / 60

    def wave(a: float, x: float) -> float:
        return a * math.sin(2 * math.pi * (x - 9) / 24)

    if cap == "t" and k == "sauna":
        ago = (now - ts).total_seconds() / 60
        return (
            round(22 + (cur - 22) * (1 - ago / 30), 1)
            if ago < 30
            else (78.0 if lt.weekday() in (4, 5) and 18 <= h < 20 else 22.0)
        )
    if cap in ("t", "h"):
        a = (3.0 if out or k == "boiler" else 0.3 if k in ("trv", "floor") else 0.6) * (1 if cap == "t" else -4)
        return round(cur + wave(a, h) - wave(a, hn) + rnd.gauss(0, 0.06 if cap == "t" else 0.4), 1)
    if cap == "lux":
        return round(max(0.0, 260 * math.sin(math.pi * (h - 8.3) / 8.6)) if 8.3 < h < 16.9 else rnd.uniform(0, 3))
    if cap == "w":
        if k == "meter":
            return round(
                420
                + (1500 if 7 <= h < 9 or 17 <= h < 22 else 0)
                + rnd.gauss(0, 110)
                + (6000 if lt.weekday() in (4, 5) and 17 <= h < 19 else 0)
            )
        if k == "boiler":
            return round(2000 + rnd.gauss(0, 10), 1) if 2 <= h < 5 else 0.0
        if cur < 10:
            return 1350.0 if lt.minute < 10 and lt.hour in (7, 8, 12, 15) else round(3.1 + rnd.gauss(0, 0.1), 1)
        return round(rnd.uniform(60, 140), 1) if lt.weekday() < 5 and 8 <= h < 18 else 1.8
    if cap in ("pm25", "voc_index"):
        return max(1, round(cur + rnd.gauss(0, max(1.0, cur * 0.15))))
    if cap == "v":
        return round(230 + rnd.gauss(0, 1.2), 1)
    if cap == "pos":
        return 100.0 if 7.5 <= h < 21 else 0.0
    return cur


async def history(devs: list[dict[str, Any]], sc: dict[str, Any]) -> None:
    import asyncpg

    conn = await asyncpg.connect(os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://"))
    try:
        if await conn.fetchval("select exists(select 1 from stats)"):
            return
        tz, now = ZoneInfo(sc["home"]["timezone"]), datetime.now(UTC)
        outdoor = {r["id"] for r in sc["rooms"] if r.get("outdoor")}
        caps = {"t", "h", "lux", "w", "pm25", "voc_index", "v", "pos", "sp"}
        raw, hourly = [], []
        for d in devs:
            for c in d["caps"]:
                cur = d["state"].get(c["id"])
                if (
                    c["id"] not in caps
                    or c.get("type") != "num"
                    or not isinstance(cur, (int, float))
                    or isinstance(cur, bool)
                ):
                    continue
                rnd, out = random.Random(f"{d['id']}:{c['id']}"), d.get("roomId") in outdoor
                first = now.replace(minute=0, second=0, microsecond=0) - timedelta(
                    days=int(os.environ.get("MOCKS_HISTORY_DAYS", "10"))
                )
                hour = first
                while hour < now - timedelta(hours=4):
                    vals = [
                        value(c["id"], cur, d, hour + timedelta(minutes=m), now, tz, out, rnd) for m in range(0, 60, 10)
                    ]
                    hourly.append((d["id"], c["id"], hour, sum(vals) / 6, min(vals), max(vals), vals[-1], 6))
                    hour += timedelta(hours=1)
                ts = now - timedelta(hours=26)
                while ts < now - timedelta(minutes=5):
                    raw.append((d["id"], c["id"], ts, float(value(c["id"], cur, d, ts, now, tz, out, rnd))))
                    ts += timedelta(minutes=10)
        await conn.copy_records_to_table("history", records=raw, columns=["device_id", "cap", "ts", "num"])
        await conn.copy_records_to_table(
            "stats", records=hourly, columns=["device_id", "cap", "hour", "mean", "min", "max", "last", "n"]
        )
        log.info("history backfilled, %s raw points, %s hourly stats", len(raw), len(hourly))
    finally:
        await conn.close()
