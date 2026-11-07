import asyncio
import json
import math
import random
import time
from typing import Any

from valo_sdk import Extension

ext = Extension()
cams: list[str] = []
SETTINGS: dict[str, Any] = {
    "motion_enabled": True,
    "motion_sensitivity": 4,
    "daynight_mode": "auto",
    "privacy": False,
    "brightness": 128,
    "hflip": False,
}
SPEC: dict[str, dict[str, Any]] = {
    "motion_enabled": {"section": "motion", "type": "bool"},
    "motion_sensitivity": {"section": "motion", "type": "int", "min": 1, "max": 8, "step": 1},
    "daynight_mode": {"section": "daynight", "type": "select", "options": ["auto", "day", "night"]},
    "privacy": {"section": "privacy", "type": "bool"},
    "brightness": {"section": "image", "type": "int", "min": 0, "max": 255, "step": 1},
    "hflip": {"section": "image", "type": "bool"},
}
values: dict[str, dict[str, Any]] = {}
positions: dict[str, dict[str, int]] = {}
booted: dict[str, float] = {}


def _store() -> dict[str, Any]:
    f = ext.data / "cameras.json"
    try:
        return json.loads(f.read_text()) if f.exists() else {}
    except ValueError:
        return {}


def _save() -> None:
    ext.data.mkdir(parents=True, exist_ok=True)
    (ext.data / "cameras.json").write_text(json.dumps({"values": values, "positions": positions}))


def _fields(cid: str) -> list[dict[str, Any]]:
    cur = values.setdefault(cid, dict(SETTINGS))
    out = [{"key": k, "value": cur.get(k, SETTINGS[k]), **spec} for k, spec in SPEC.items()]
    out.append({"key": "main_size", "section": "streams", "type": "info", "value": "1280x720 H264"})
    out.append({"key": "clock_drift", "section": "time", "type": "info", "value": 0, "unit": "s"})
    return out


ext.device(
    "motion-1",
    "Sim motion",
    [{"id": "occ", "type": "bool", "access": "r"}, {"id": "bat", "type": "num", "unit": "%", "access": "r"}],
    kind="motion",
    service=False,
)
ext.device(
    "temp-1",
    "Sim temperature",
    [{"id": "t", "type": "num", "unit": "°C", "access": "r"}, {"id": "h", "type": "num", "unit": "%", "access": "r"}],
    kind="clim",
    service=False,
)


@ext.loop
async def tick() -> None:
    while True:
        x = time.time() / 600
        await ext.state("temp-1", {"t": round(21 + 1.5 * math.sin(x), 1), "h": round(40 + 5 * math.cos(x), 1)})
        if random.random() < 0.3:
            await ext.state("motion-1", {"occ": True, "bat": 97})
            await asyncio.sleep(5)
            await ext.state("motion-1", {"occ": False, "bat": 97})
        await asyncio.sleep(float(ext.settings.get("period") or 20))


@ext.camera_probe
async def camera_probe(cfg: dict) -> dict:
    pattern = "door" if cfg.get("pattern") == "door" else "yard"
    return {
        "streams": {"main": f"rtsp://127.0.0.1:8554/demo-{pattern}"},
        "info": {
            "vendor": "Valo",
            "model": f"Demo camera {pattern}",
            "mac": f"demo-{pattern}",
            "ptz": pattern == "door",
        },
    }


@ext.camera_sync
async def camera_sync(cameras: list) -> dict:
    if not values and not positions:
        st = _store()
        values.update(st.get("values") or {})
        positions.update(st.get("positions") or {})
    cams[:] = [c["id"] for c in cameras if c.get("id")]
    for cid in cams:
        if time.time() > booted.get(cid, 0):
            await ext.available(cid, True)
            await ext.camera_health(cid, "ok")
    return {"cameras": cams}


@ext.camera_feature("settings")
async def camera_settings(params: dict) -> dict:
    cid = str(params.get("camera") or "")
    failed: dict[str, str] = {}
    if params.get("op") == "set":
        cur = values.setdefault(cid, dict(SETTINGS))
        for k, v in (params.get("values") or {}).items():
            spec = SPEC.get(k)
            if spec is None:
                failed[k] = "setting is not supported"
            elif spec["type"] == "int" and not (isinstance(v, int) and spec["min"] <= v <= spec["max"]):
                failed[k] = f"value must be from {spec['min']} to {spec['max']}"
            elif spec["type"] == "select" and v not in spec["options"]:
                failed[k] = "unknown option"
            else:
                cur[k] = bool(v) if spec["type"] == "bool" else v
        _save()
    return {"fields": _fields(cid), "failed": failed}


async def _reboot(cid: str) -> None:
    booted[cid] = time.time() + 20
    await ext.available(cid, False)
    await ext.camera_health(cid, "offline", "rebooting")
    await asyncio.sleep(20)
    await ext.available(cid, True)
    await ext.camera_health(cid, "ok")


@ext.camera_feature("actions")
async def camera_actions(params: dict) -> dict:
    cid, name = str(params.get("camera") or ""), params.get("action")
    if name == "reboot":
        ext.spawn(_reboot(cid))
        return {"ok": True, "detail": "rebooting, about 20 s"}
    if name in ("restart_stream", "sync_time"):
        return {"ok": True, "detail": str((params.get("params") or {}).get("timezone") or "")}
    raise ValueError(f"action {name} is not supported")


@ext.camera_feature("diagnose")
async def camera_diagnose(params: dict) -> dict:
    up = time.time() > booted.get(str(params.get("camera") or ""), 0)
    return {
        "checks": [
            {"key": "network", "ok": up, "value": "127.0.0.1"},
            {"key": "rtsp_main", "ok": up, "value": "demo"},
            {"key": "uptime", "ok": up, "value": int(time.monotonic())},
            {"key": "clock", "ok": True, "value": 0},
        ]
    }


@ext.camera_feature("discover")
async def camera_discover(params: dict) -> dict:
    info = params.get("info") or {}
    return {"found": [{"host": "127.0.0.1", "mac": info.get("mac", ""), "model": info.get("model", ""), "same": True}]}


@ext.camera_feature("ptz")
async def camera_ptz(params: dict) -> dict:
    cid, op = str(params.get("camera") or ""), params.get("op")
    if not (params.get("info") or {}).get("ptz"):
        raise ValueError("this camera has no motors")
    pos = positions.setdefault(cid, {"x": 2000, "y": 1000})
    if op == "move":
        pos["x"] = max(0, min(4000, pos["x"] + round(float(params.get("pan") or 0) * 1000)))
        pos["y"] = max(0, min(2000, pos["y"] + round(float(params.get("tilt") or 0) * 500)))
    elif op in ("home", "calibrate"):
        pos.update(x=2000, y=1000)
    elif op == "goto":
        p = params.get("position") or {}
        pos.update(x=int(p.get("x", pos["x"])), y=int(p.get("y", pos["y"])))
    _save()
    return {"position": dict(pos)}


@ext.loop
async def camera_motion() -> None:
    while True:
        await asyncio.sleep(random.uniform(60, 150))
        if not cams:
            continue
        cid = random.choice(cams)
        try:
            await ext.camera_event(cid, "motion", True)
            await asyncio.sleep(random.uniform(4, 12))
            await ext.camera_event(cid, "motion", False)
        except Exception as e:
            ext.log.warning("camera %s motion not reported: %s", cid, e)


@ext.block("simulate")
async def simulate(params: dict, token: dict, dry: bool) -> dict:
    occ = bool(params.get("occ", True))
    if not dry:
        await ext.state("motion-1", {"occ": occ})
    return {"outs": [[0]], "trace": {"s": "skip" if dry else "ok", "m": "ext_simulated", "p": {"value": occ}}}


if __name__ == "__main__":
    ext.run()
