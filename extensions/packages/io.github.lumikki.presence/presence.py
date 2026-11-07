import asyncio
import time

from valo_sdk import Extension

ext = Extension()
seen: dict[str, float] = {}
rooms: dict[str, str] = {}
state: dict[str, bool] = {}


@ext.on_start
async def start() -> None:
    timeout = float(ext.settings.get("timeout") or 0)
    if timeout <= 0:
        raise ValueError(f"setting timeout must be positive, got {timeout}")
    for d in await ext.call("devices.list"):
        if d.get("kind") in ("motion", "contact") and d.get("roomId"):
            rooms[d["id"]] = d["roomId"]
    caps = [{"id": r, "type": "bool", "access": "r"} for r in sorted(set(rooms.values()))]
    ext.device("rooms", "Presence", caps, kind="presence")
    await ext._pub(f"{ext.base}/dev/rooms/meta", {"name": "Presence", "caps": caps, "kind": "presence"}, retain=True)
    ext.log.info("tracking %s sensors in %s rooms", len(rooms), len(caps))


@ext.subscribe("hub/v1/core/state/+")
async def on_state(topic: str, payload: dict) -> None:
    dev = topic.rsplit("/", 1)[-1]
    if dev in rooms and (payload.get("occ") or payload.get("open")):
        seen[rooms[dev]] = time.time()


@ext.loop
async def update() -> None:
    while True:
        limit = float(ext.settings.get("timeout") or 10) * 60
        now = time.time()
        cur = {r: now - seen.get(r, 0) < limit for r in set(rooms.values())}
        for r, busy in cur.items():
            if state.get(r) and not busy:
                await ext.trigger("empty", {"room": r})
        if cur != state:
            state.update(cur)
            await ext.state("rooms", cur)
        await asyncio.sleep(15)


if __name__ == "__main__":
    ext.run()
