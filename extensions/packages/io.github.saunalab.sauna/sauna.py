import time

from valo_sdk import Extension

ext = Extension()
ext.device(
    "session",
    "Sauna session",
    [
        {"id": "phase", "type": "enum", "values": ["off", "heating", "ready"], "access": "r"},
        {"id": "eta", "type": "num", "unit": "min", "access": "r"},
        {"id": "t", "type": "num", "unit": "°C", "access": "r"},
    ],
    kind="sauna",
)
hist: list[tuple[float, float]] = []
phase = {"v": "off"}


@ext.subscribe("hub/v1/core/state/+")
async def on_state(topic: str, payload: dict) -> None:
    if topic.rsplit("/", 1)[-1] != str(ext.settings.get("device") or "sauna-ctrl"):
        return
    target = float(ext.settings.get("ready") or 75)
    t, on = payload.get("t"), payload.get("on")
    if isinstance(t, (int, float)):
        hist.append((time.time(), float(t)))
        del hist[:-20]
    if on is False:
        phase["v"] = "off"
    elif on is True and phase["v"] == "off":
        phase["v"] = "heating"
    cur = hist[-1][1] if hist else None
    eta = None
    if phase["v"] == "heating" and cur is not None and len(hist) > 2:
        (t0, v0), (t1, v1) = hist[0], hist[-1]
        rate = (v1 - v0) / max(t1 - t0, 1)
        eta = round((target - cur) / rate / 60, 1) if rate > 0 else None
    if phase["v"] == "heating" and cur is not None and cur >= target:
        phase["v"] = "ready"
        await ext.trigger("ready", {"t": cur})
        ext.log.info("sauna ready at %s", cur)
    await ext.state("session", {"phase": phase["v"], "eta": eta, "t": cur})


if __name__ == "__main__":
    ext.run()
