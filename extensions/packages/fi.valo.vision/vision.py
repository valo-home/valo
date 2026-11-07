import asyncio
import time
from typing import Any

import visionlogic as vl
from valo_sdk import Extension

ext = Extension()
cams: dict[str, dict[str, Any]] = {}
by_device: dict[str, str] = {}
moving: dict[str, bool] = {}
until: dict[str, float] = {}
workers: dict[str, asyncio.Task] = {}
detector: vl.Detector | None = None
refreshed = 0.0


def setting(key: str, default: float, lo: float, hi: float) -> float:
    try:
        return max(lo, min(float(ext.settings.get(key) or default), hi))
    except TypeError, ValueError:
        return default


async def refresh() -> None:
    global refreshed
    refreshed = time.monotonic()
    rows = await ext.cameras()
    cams.clear()
    by_device.clear()
    for c in rows or []:
        if isinstance(c, dict) and c.get("id"):
            cams[c["id"]] = c
            if c.get("deviceId"):
                by_device[c["deviceId"]] = c["id"]
    on = sorted(cid for cid, c in cams.items() if (c.get("detect") or {}).get("enabled"))
    ext.log.info("cameras %d, recognition on %s", len(cams), ", ".join(on) or "none")


@ext.on_start
async def start() -> None:
    global detector
    detector = await asyncio.to_thread(vl.Detector)
    ext.log.info("model %s loaded", vl.MODEL.name)
    await refresh()


@ext.subscribe("hub/v1/core/state/+")
async def on_state(topic: str, payload: Any) -> None:
    if not isinstance(payload, dict) or "occ" not in payload:
        return
    dev = topic.rsplit("/", 1)[-1]
    cid = by_device.get(dev)
    if cid is None:
        if time.monotonic() - refreshed > 30:
            await refresh()
            cid = by_device.get(dev)
        if cid is None:
            return
    active = bool(payload["occ"])
    if active and time.monotonic() - refreshed > 30:
        await refresh()
    if cid not in cams:
        return
    moving[cid] = active
    until[cid] = time.monotonic() + setting("hold_s", 6, 2, 60)
    if not active or not (cams[cid].get("detect") or {}).get("enabled"):
        return
    if cid not in workers or workers[cid].done():
        workers[cid] = asyncio.ensure_future(watch(cid))


async def frame(cid: str, sub: bool) -> bytes:
    return await ext.camera_frame(cid, sub=sub, fresh=True)


async def report(cid: str, track: vl.Tracker, started: list[vl.Det], ended: list[str], data: bytes) -> None:
    for lb in ended:
        await ext.camera_event(cid, lb, False)
    if not started:
        return
    shot = data
    try:
        shot = await frame(cid, sub=False)
    except Exception as e:
        ext.log.info("camera %s main frame unavailable, using analysed frame: %s", cid, e)
    for d in started:
        res = await ext.camera_event(cid, d.label, True, round(d.score, 3), d.view())
        eid = res.get("event") if isinstance(res, dict) else None
        if track.active.get(d.label) is not None:
            track.active[d.label]["event"] = eid
        if eid is not None:
            img = await asyncio.to_thread(vl.draw, shot, [x for x in started if x.label == d.label])
            await ext.media_put(cid, img, event=eid, label=d.label, meta=d.view())
        ext.log.info("camera %s %s %.2f zone %s", cid, d.label, d.score, d.zone or "-")


async def watch(cid: str) -> None:
    """Анализ кадров камеры, пока идет движение и hold секунд после, но не дольше max_s."""
    track = vl.Tracker(hold=setting("hold_s", 6, 2, 60))
    period = 1 / setting("fps", 1, 0.2, 4)
    deadline = time.monotonic() + setting("max_s", 300, 10, 3600)
    frames, fetch, infer, fails = 0, 0.0, 0.0, 0
    ext.log.info("camera %s analysis started", cid)
    try:
        while time.monotonic() < deadline and (moving.get(cid) or time.monotonic() < until.get(cid, 0)):
            cam = cams.get(cid) or {}
            detect = cam.get("detect") or {}
            if not detect.get("enabled") or detector is None:
                break
            t0 = time.monotonic()
            try:
                data = await frame(cid, sub=True)
                fails = 0
            except Exception as e:
                fails += 1
                ext.log.warning("camera %s frame failed (%d): %s", cid, fails, e)
                if fails >= 3:
                    break
                await asyncio.sleep(2)
                continue
            t1 = time.monotonic()
            try:
                raw = await asyncio.to_thread(detector.run, data)
                dets = vl.select(raw, detect, cam.get("zones") or [])
                started, ended = track.step(dets, time.monotonic())
                await report(cid, track, started, ended, data)
            except Exception as e:
                fails += 1
                ext.log.exception("camera %s analysis step failed (%d): %s", cid, fails, e)
                if fails >= 3:
                    break
            frames += 1
            fetch += t1 - t0
            infer += time.monotonic() - t1
            await asyncio.sleep(max(0.05, period - (time.monotonic() - t0)))
    finally:
        for lb in track.close():
            try:
                await ext.camera_event(cid, lb, False)
            except Exception as e:
                ext.log.error("camera %s %s end not reported: %s", cid, lb, e)
        n = max(frames, 1)
        ext.log.info(
            "camera %s analysis stopped, %d frames, frame %.0f ms, recognition %.0f ms",
            cid,
            frames,
            fetch / n * 1000,
            infer / n * 1000,
        )


@ext.loop
async def resync() -> None:
    while True:
        await asyncio.sleep(60)
        try:
            await refresh()
        except Exception as e:
            ext.log.warning("camera list refresh failed: %s", e)


if __name__ == "__main__":
    ext.run()
