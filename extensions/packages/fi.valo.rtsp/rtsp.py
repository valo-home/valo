import asyncio
from typing import Any
from urllib.parse import urlsplit

from valo_camera import CameraError, rtsp_check, with_auth
from valo_sdk import Extension

ext = Extension()
watchers: dict[str, asyncio.Task] = {}
configs: dict[str, dict[str, Any]] = {}


def stream(cfg: dict[str, Any], key: str) -> str:
    raw = str(cfg.get(key) or "").strip()
    if not raw:
        return ""
    if not raw.startswith(("rtsp://", "rtsps://")):
        raise CameraError(f"{key} stream address must start with rtsp://")
    return with_auth(raw, str(cfg.get("user") or ""), str(cfg.get("password") or "")) if cfg.get("user") else raw


def still(cfg: dict[str, Any]) -> str:
    raw = str(cfg.get("snapshot") or "").strip()
    if raw and not raw.startswith(("http://", "https://")):
        raise CameraError("snapshot address must start with http:// or https://")
    return raw


@ext.camera_probe
async def probe(cfg: dict[str, Any]) -> dict[str, Any]:
    main = stream(cfg, "main")
    if not main:
        raise CameraError("main stream address is required")
    await rtsp_check(main)
    sub = stream(cfg, "sub")
    if sub:
        await rtsp_check(sub)
    snap = still(cfg)
    host = urlsplit(main).hostname or ""
    ext.log.info("camera %s ok", host)
    return {
        "streams": {"main": main, "sub": sub},
        "stills": {"snapshot": snap, "preview": snap} if snap else {},
        "info": {
            "vendor": str(cfg.get("vendor") or "RTSP"),
            "model": str(cfg.get("model") or "RTSP"),
            "hostname": host,
        },
        "caps": [],
    }


async def watch(cid: str, cfg: dict[str, Any]) -> None:
    online = None
    while True:
        try:
            await rtsp_check(stream(cfg, "main"))
            alive = True
        except CameraError as e:
            alive = False
            if online is not False:
                ext.log.warning("camera %s unavailable: %s", cid, e)
        if alive != online:
            try:
                await ext.available(cid, alive)
                online = alive
            except Exception as e:
                ext.log.error("camera %s availability not reported: %s", cid, e)
        await asyncio.sleep(60)


@ext.camera_sync
async def sync(cameras: list[dict[str, Any]]) -> dict[str, Any]:
    wanted = {c["id"]: c.get("config") or {} for c in cameras if c.get("id")}
    for cid in list(watchers):
        if cid not in wanted or configs.get(cid) != wanted[cid]:
            watchers.pop(cid).cancel()
            configs.pop(cid, None)
    for cid, cfg in wanted.items():
        if cid not in watchers or watchers[cid].done():
            configs[cid] = cfg
            watchers[cid] = asyncio.ensure_future(watch(cid, cfg))
    return {"watching": sorted(watchers)}


if __name__ == "__main__":
    ext.run()
