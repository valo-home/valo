import asyncio
import base64
import io
import json
import logging
import math
import os
import pathlib
import random
import time
import uuid
import zipfile
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

import aiomqtt

log = logging.getLogger("mocks.sim")
Z = os.environ.get("Z2M_BASE_TOPIC", "zigbee2mqtt")
SPEED = float(os.environ.get("MOCKS_SPEED", "1"))
CTL = "valo-mocks/ctl"
BOILER = "esphome-boiler"
STATE = os.environ.get("MOCKS_STATE", "")


def client(**kw: Any) -> aiomqtt.Client:
    return aiomqtt.Client(
        os.environ.get("MQTT_HOST", "localhost"),
        int(os.environ.get("MQTT_PORT", "1883")),
        username=os.environ.get("MOCKS_MQTT_USER", "valo-mocks"),
        password=os.environ.get("MOCKS_MQTT_PASSWORD") or None,
        identifier=f"valo-mocks-{uuid.uuid4().hex[:8]}",
        protocol=aiomqtt.ProtocolVersion.V5,
        **kw,
    )


def b(p: str, a: int = 1, on: Any = True, off: Any = False) -> dict[str, Any]:
    return {"type": "binary", "name": p, "property": p, "access": a, "value_on": on, "value_off": off}


def n(
    p: str,
    a: int = 1,
    unit: str | None = None,
    lo: float | None = None,
    hi: float | None = None,
    step: float | None = None,
) -> dict[str, Any]:
    e: dict[str, Any] = {"type": "numeric", "name": p, "property": p, "access": a}
    e.update(
        {k: v for k, v in (("unit", unit), ("value_min", lo), ("value_max", hi), ("value_step", step)) if v is not None}
    )
    return e


def en(p: str, values: list[str], a: int = 1) -> dict[str, Any]:
    return {"type": "enum", "name": p, "property": p, "access": a, "values": values}


ON, BAT, SWITCH = (
    b("state", 7, "ON", "OFF"),
    n("battery", 1, "%", 0, 100),
    {"type": "switch", "features": [b("state", 7, "ON", "OFF")]},
)
EXPOSES = {
    "light_ct": [
        {"type": "light", "features": [ON, n("brightness", 7, None, 0, 254), n("color_temp", 7, "mired", 250, 454)]}
    ],
    "relay_light": [SWITCH],
    "relay": [SWITCH],
    "light_rgb": [
        {
            "type": "light",
            "features": [
                ON,
                n("brightness", 7, None, 0, 254),
                {
                    "type": "composite",
                    "name": "color_xy",
                    "property": "color",
                    "access": 7,
                    "features": [n("x", 7), n("y", 7)],
                },
            ],
        }
    ],
    "relay2": [
        {"type": "switch", "endpoint": ep, "features": [{**b(f"state_{ep}", 7, "ON", "OFF"), "endpoint": ep}]}
        for ep in ("l1", "l2")
    ],
    "plug": [SWITCH, n("power", 5, "W"), n("energy", 5, "kWh"), n("voltage", 5, "V"), n("current", 5, "A")],
    "clim": [n("temperature", 1, "°C"), n("humidity", 1, "%"), BAT],
    "air": [n("temperature", 1, "°C"), n("humidity", 1, "%"), n("pm25", 1, "µg/m³"), n("voc_index", 1)],
    "trv": [
        {
            "type": "climate",
            "features": [
                n("occupied_heating_setpoint", 7, "°C", 5, 35, 0.5),
                n("local_temperature", 5, "°C"),
                en("running_state", ["idle", "heat"], 5),
            ],
        },
        BAT,
    ],
    "floor": [
        {
            "type": "climate",
            "features": [
                n("current_heating_setpoint", 7, "°C", 5, 35, 0.5),
                n("local_temperature", 1, "°C"),
                en("running_state", ["idle", "heat"]),
            ],
        },
        b("child_lock", 3, "LOCK", "UNLOCK"),
    ],
    "remote": [
        en(
            "action",
            [
                "on",
                "off",
                "brightness_move_up",
                "brightness_move_down",
                "brightness_stop",
                "arrow_left_click",
                "arrow_right_click",
            ],
        ),
        BAT,
    ],
    "motion": [b("occupancy"), n("illuminance", 1, "lx"), BAT],
    "contact": [b("contact"), BAT],
    "leak": [b("water_leak"), BAT],
    "blind": [
        {"type": "cover", "features": [en("state", ["OPEN", "CLOSE", "STOP"], 3), n("position", 7, "%", 0, 100)]},
        BAT,
    ],
}
DESC = {
    "929002994901": "Hue Play gradient lightstrip",
    "TS0012": "Wall switch, 2 gang",
    "LED1545G12": "TRADFRI bulb E26/E27, white spectrum, globe, opal, 980 lm",
    "7146060PH": "Hue Go",
    "WSDCGQ11LM": "Temperature, humidity and pressure sensor",
    "014G2461": "Ally thermostat",
    "E2001/E2002": "STYRBAR remote control",
    "E2112": "VINDSTYRKA air quality and humidity sensor",
    "ZBMINI": "Zigbee two way smart switch",
    "ZNCZ02LM": "Mi power plug ZigBee",
    "SJCGQ11LM": "Water leak sensor",
    "RTCGQ11LM": "Motion sensor",
    "SNZB-02": "Temperature and humidity sensor",
    "MCCGQ11LM": "Door and window sensor",
    "E1743": "TRADFRI ON/OFF switch",
    "TS0601": "Floor heating thermostat",
    "TS011F": "Smart plug with power monitoring",
    "E1757": "FYRTUR roller blind",
}
SW = {
    "IKEA": "2.3.093",
    "Philips": "1.104.2",
    "Aqara": "3000-0001",
    "Xiaomi": "3000-0001",
    "Sonoff": "1.0.5",
    "Danfoss": "1.16",
}
PERIOD = {
    "clim": 90,
    "air": 60,
    "trv": 600,
    "floor": 300,
    "plug": 60,
    "light_ct": 3600,
    "relay_light": 3600,
    "relay": 3600,
    "light_rgb": 3600,
    "relay2": 3600,
}
R = {
    "h": "humidity",
    "bat": "battery",
    "occ": "occupancy",
    "lux": "illuminance",
    "leak": "water_leak",
    "w": "power",
    "kwh": "energy",
    "pos": "position",
    "voc": "voc_index",
    "lock": "child_lock",
}


def props(items: list[dict[str, Any]], out: dict[str, Any] | None = None) -> dict[str, Any]:
    out = {} if out is None else out
    for e in items:
        if e.get("type") == "composite" and e.get("property"):
            out[e["property"]] = e
        elif e.get("features"):
            props(e["features"], out)
        elif e.get("property"):
            out[e["property"]] = e
    return out


WRITABLE = {k: {p for p, e in props(v).items() if e["access"] & 2} for k, v in EXPOSES.items()}


def z2m(kind: str, values: dict[str, Any]) -> dict[str, Any]:
    p: dict[str, Any] = {}
    for k, v in values.items():
        if k == "on":
            p["state"] = "ON" if v else "OFF"
        elif k.startswith("on_"):
            p[f"state_{k[3:]}"] = "ON" if v else "OFF"
        elif k == "color":
            p["color"] = {"hex": v}
        elif k == "bri":
            p["brightness"] = round(v * 254 / 100)
        elif k == "ct":
            p["color_temp"] = round(1e6 / v)
        elif k == "t":
            p["local_temperature" if kind in ("trv", "floor") else "temperature"] = v
        elif k == "sp":
            p["occupied_heating_setpoint" if kind == "trv" else "current_heating_setpoint"] = v
        elif k == "heat":
            p["running_state"] = "heat" if v else "idle"
        elif k == "open":
            p["contact"] = not v
        else:
            p[R.get(k, k)] = v
    return p


class Sim:
    def __init__(self, sc: dict[str, Any]) -> None:
        self.sc, self.c = sc, None
        self.tz = ZoneInfo(sc["home"]["timezone"])
        self.outdoor = {r["id"] for r in sc["rooms"] if r.get("outdoor")}
        self.devs = [self.zdev(d) for d in sc["zigbee"]] + [self.zdev(sc["joiner"], False)]
        self.hub = {
            h["key"]: {**h, "st": dict(h["state"]), "x": h["state"].get("t", 0), "next": 0.0} for h in sc["hub"]
        }
        self.boiler = {"on": bool(sc["ha"][0]["state"]["on"]), "w": 0.0, "t": 61.0, "next": 0.0}
        self.converters: dict[str, str] = {}
        self.permit_end, self.channel, self.restart_required, self.garage_next = (
            0.0,
            sc["coordinator"]["channel"],
            False,
            0.0,
        )
        self.tasks: set[asyncio.Task] = set()
        self.restore()

    def restore(self) -> None:
        if not STATE or not pathlib.Path(STATE).exists():
            return
        data = json.loads(pathlib.Path(STATE).read_text("utf-8"))
        self.converters, self.channel = data.get("converters", {}), data.get("channel", self.channel)
        self.sc["coordinator"]["channel"] = data.get("net", self.sc["coordinator"]["channel"])
        for d in self.devs:
            d.update(data.get("devs", {}).get(d["key"], {}))
        log.info("state restored from %s", STATE)

    def save(self) -> None:
        if STATE:
            keys = ("joined", "fn", "sw", "update", "offline")
            data = {
                "converters": self.converters,
                "channel": self.channel,
                "net": self.sc["coordinator"]["channel"],
                "devs": {d["key"]: {k: d[k] for k in keys} for d in self.devs},
            }
            pathlib.Path(STATE).write_text(json.dumps(data), "utf-8")

    def zdev(self, d: dict[str, Any], joined: bool = True) -> dict[str, Any]:
        st = z2m(d["kind"], d["state"])
        if d["kind"] == "plug":
            st.update(voltage=230.4, current=round(st.get("power", 0) / 230.4, 3))
        upd = (
            {"state": "available", "installed_version": d["ota"]["installed"], "latest_version": d["ota"]["latest"]}
            if d.get("ota")
            else None
        )
        x = st.get("local_temperature", 0)
        return {
            **d,
            "room": d.get("room"),
            "fn": d["key"] if joined else d["ieee"],
            "st": st,
            "pub": {},
            "joined": joined,
            "offline": bool(d.get("offline")),
            "base": dict(d["state"]),
            "update": upd,
            "sw": (d.get("ota") or {}).get("installed") or SW.get(d["vendor"]),
            "next": time.time() + random.uniform(10, PERIOD.get(d["kind"], 3000)) / SPEED,
            "seen": time.time(),
            "x": x,
            "kwh": st.get("energy", 0),
        }

    def active(self) -> list[dict[str, Any]]:
        return [d for d in self.devs if d["joined"]]

    def find(self, ident: Any) -> dict[str, Any] | None:
        return next((d for d in self.active() if ident in (d["fn"], d["ieee"])), None)

    def spawn(self, coro: Any) -> None:
        async def guard() -> None:
            try:
                await coro
            except Exception:
                log.exception("task failed")

        t = asyncio.ensure_future(guard())
        self.tasks.add(t)
        t.add_done_callback(self.tasks.discard)

    async def pub(self, topic: str, payload: Any, retain: bool = False) -> None:
        assert self.c is not None
        body = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
        await self.c.publish(topic, body, qos=1, retain=retain)

    async def state(self, d: dict[str, Any], **extra: Any) -> None:
        d["seen"], d["pub"] = time.time(), dict(d["st"])
        lqi = max(1, min(255, d["lqi"] + random.randint(-6, 6)))
        body = {**d["st"], "linkquality": lqi, **extra} if self.supported(d) else {"linkquality": lqi}
        if d["update"]:
            body["update"] = d["update"]
        await self.pub(f"{Z}/{d['fn']}", body, True)

    async def avail(self, d: dict[str, Any]) -> None:
        await self.pub(f"{Z}/{d['fn']}/availability", {"state": "offline" if d["offline"] else "online"}, True)

    def supported(self, d: dict[str, Any]) -> bool:
        return d["model"] != "TS0601" or any("ts0601" in k.lower() for k in self.converters)

    def definition(self, d: dict[str, Any]) -> dict[str, Any] | None:
        if not self.supported(d):
            return None
        return {
            "model": d["model"],
            "vendor": d["vendor"],
            "description": DESC.get(d["model"], d["model"]),
            "exposes": EXPOSES[d["kind"]],
            "options": [],
            "supports_ota": bool(d["update"]) or d["vendor"] in ("IKEA", "Philips"),
            "source": "external" if d["model"] == "TS0601" else "native",
        }

    def item(self, d: dict[str, Any]) -> dict[str, Any]:
        df = self.definition(d)
        generated = {
            "model": d["model"],
            "vendor": d["vendor"],
            "description": "Automatically generated definition",
            "exposes": [],
            "options": [],
            "supports_ota": False,
            "source": "generated",
        }
        return {
            "ieee_address": d["ieee"],
            "type": "Router" if d["router"] else "EndDevice",
            "network_address": d["nwk"],
            "supported": df is not None,
            "friendly_name": d["fn"],
            "disabled": False,
            "description": None,
            "definition": df or generated,
            "power_source": "Mains (single phase)" if d["router"] else "Battery",
            "software_build_id": d["sw"],
            "model_id": d["model"],
            "manufacturer": d["vendor"],
            "interviewing": False,
            "interview_completed": True,
            "interview_state": "SUCCESSFUL",
        }

    def info(self) -> dict[str, Any]:
        c = self.sc["coordinator"]
        major, minor, patch = (int(x) for x in c["revision"].split(".")[:3])
        on = self.permit_end > time.time()
        return {
            "version": "2.6.2",
            "commit": "5c1d2a7",
            "coordinator": {
                "ieee_address": c["ieee"],
                "type": c["type"],
                "meta": {"revision": c["revision"], "major": major, "minor": minor, "patch": patch, "ezsp": 13},
            },
            "network": {"channel": c["channel"], "pan_id": c["pan"], "extended_pan_id": "0x5a1e6e9ebc3f0d21"},
            "log_level": "info",
            "permit_join": on,
            "permit_join_end": int(self.permit_end * 1000) if on else None,
            "restart_required": self.restart_required,
            "config": {
                "serial": {"port": c["port"], "adapter": "ember"},
                "advanced": {"channel": self.channel, "pan_id": c["pan"], "log_level": "info"},
                "availability": {"enabled": True, "active": {"timeout": 10}, "passive": {"timeout": 1500}},
                "ota": {"update_check_interval": 1440, "disable_automatic_update_check": False},
                "homeassistant": {"enabled": False},
                "mqtt": {"base_topic": Z},
            },
        }

    async def bridge(self, devices: bool = True) -> None:
        await self.pub(f"{Z}/bridge/info", self.info(), True)
        if devices:
            c = self.sc["coordinator"]
            coord = {
                "ieee_address": c["ieee"],
                "type": "Coordinator",
                "network_address": 0,
                "supported": True,
                "friendly_name": "Coordinator",
                "disabled": False,
                "definition": None,
                "power_source": None,
                "interview_completed": True,
                "interview_state": "SUCCESSFUL",
                "interviewing": False,
            }
            await self.pub(f"{Z}/bridge/devices", [coord, *[self.item(d) for d in self.active()]], True)

    async def boot(self) -> None:
        await self.pub(f"{Z}/bridge/state", {"state": "online"}, True)
        await self.bridge()
        await self.pub(f"{Z}/bridge/groups", [], True)
        await self.pub(f"{Z}/bridge/converters", [{"name": k, "code": v} for k, v in self.converters.items()], True)
        for d in self.active():
            await self.avail(d)
            if not d["offline"]:
                await self.state(d)
        for h in self.hub.values():
            base = f"hub/v1/dev/{h['key']}"
            await self.pub(f"{base}/meta", {k: h[k] for k in ("name", "model", "vendor", "kind", "caps")}, True)
            await self.pub(f"{base}/avail", "online", True)
            await self.pub(f"{base}/state", h["st"], True)
        dev = {"ids": BOILER, "name": BOILER, "mf": "Espressif", "mdl": "esp32dev", "sw": "esphome v2025.10.1"}
        common = {"avty_t": f"{BOILER}/status", "dev": dev, "o": {"name": "ESPHome", "sw": "2025.10.1"}}
        await self.pub(
            f"homeassistant/switch/{BOILER}/relay/config",
            {
                "name": "Relay",
                "uniq_id": f"{BOILER}-relay",
                "stat_t": f"{BOILER}/switch/relay/state",
                "cmd_t": f"{BOILER}/switch/relay/command",
                **common,
            },
            True,
        )
        await self.pub(
            f"homeassistant/sensor/{BOILER}/power/config",
            {
                "name": "Power",
                "uniq_id": f"{BOILER}-power",
                "stat_t": f"{BOILER}/sensor/power/state",
                "dev_cla": "power",
                "unit_of_meas": "W",
                "stat_cla": "measurement",
                **common,
            },
            True,
        )
        await self.pub(
            f"homeassistant/sensor/{BOILER}/water/config",
            {
                "name": "Water temperature",
                "uniq_id": f"{BOILER}-water",
                "stat_t": f"{BOILER}/sensor/water/state",
                "dev_cla": "temperature",
                "unit_of_meas": "°C",
                **common,
            },
            True,
        )
        await self.pub(f"{BOILER}/status", "online", True)
        await self.boiler_state()
        g = self.sc["ghost"]
        await self.pub(g["topic"], g["config"], True)
        await self.pub(g["lwt"], "Offline", True)

    async def boiler_state(self) -> None:
        bo = self.boiler
        await self.pub(f"{BOILER}/switch/relay/state", "ON" if bo["on"] else "OFF", True)
        await self.pub(f"{BOILER}/sensor/power/state", f"{bo['w']:.1f}", True)
        await self.pub(f"{BOILER}/sensor/water/state", f"{bo['t']:.1f}", True)

    async def on_request(self, path: str, req: Any) -> None:
        req = req if isinstance(req, dict) else {}
        fn = getattr(self, "rq_" + path.replace("/", "_"), None)
        try:
            if fn is None:
                raise ValueError(f"Request '{path}' is not supported")
            body: dict[str, Any] = {"data": await fn(req), "status": "ok"}
        except Exception as e:
            log.warning("request %s failed: %s", path, e)
            body = {"data": {}, "status": "error", "error": str(e)}
        if "transaction" in req:
            body["transaction"] = req["transaction"]
        await self.pub(f"{Z}/bridge/response/{path}", body)

    def need(self, req: dict[str, Any]) -> dict[str, Any]:
        d = self.find(req.get("id"))
        if d is None:
            raise ValueError(f"Device '{req.get('id')}' does not exist")
        return d

    async def rq_permit_join(self, req: dict[str, Any]) -> dict[str, Any]:
        t = max(0, min(int(req.get("time", 0)), 254))
        self.permit_end = time.time() + t if t else 0.0
        await self.bridge(False)
        if t:
            self.spawn(self.joining(self.permit_end))
        log.info("permit join %ss", t)
        return {"time": t}

    async def joining(self, end: float) -> None:
        await asyncio.sleep(min(6, end - time.time()))
        for d in [x for x in self.devs if not x["joined"]]:
            if self.permit_end != end:
                return
            data = {"friendly_name": d["ieee"], "ieee_address": d["ieee"]}
            await self.pub(f"{Z}/bridge/event", {"type": "device_joined", "data": data})
            await asyncio.sleep(1)
            await self.pub(f"{Z}/bridge/event", {"type": "device_announce", "data": data})
            await self.pub(f"{Z}/bridge/event", {"type": "device_interview", "data": {**data, "status": "started"}})
            await asyncio.sleep(4)
            d.update(fn=d["ieee"], joined=True, offline=False)
            df = self.definition(d)
            await self.pub(
                f"{Z}/bridge/event",
                {
                    "type": "device_interview",
                    "data": {**data, "status": "successful", "supported": df is not None, "definition": df},
                },
            )
            await self.bridge()
            await self.avail(d)
            await self.state(d)
            log.info("device %s joined", d["ieee"])
            self.save()
        await asyncio.sleep(max(0.0, end - time.time()))
        if self.permit_end == end:
            self.permit_end = 0.0
            await self.bridge(False)

    async def rq_networkmap(self, req: dict[str, Any]) -> dict[str, Any]:
        await asyncio.sleep(3)
        c = self.sc["coordinator"]
        root = {"ieeeAddr": c["ieee"], "networkAddress": 0}
        nodes = [
            {
                **root,
                "friendlyName": "Coordinator",
                "type": "Coordinator",
                "manufacturerName": None,
                "modelID": None,
                "failed": [],
                "lastSeen": None,
            }
        ]
        links, by = [], {d["key"]: d for d in self.active()}

        def depth(d: dict[str, Any], k: int = 1) -> int:
            p = by.get(d["parent"])
            return k if p is None or k > 8 else depth(p, k + 1)

        for d in self.active():
            me = {"ieeeAddr": d["ieee"], "networkAddress": d["nwk"]}
            nodes.append(
                {
                    **me,
                    "friendlyName": d["fn"],
                    "type": "Router" if d["router"] else "EndDevice",
                    "manufacturerName": d["vendor"],
                    "modelID": d["model"],
                    "failed": ["lqi", "routingTable"] if d["offline"] else [],
                    "lastSeen": int(d["seen"] * 1000),
                    "definition": {
                        "model": d["model"],
                        "vendor": d["vendor"],
                        "description": DESC.get(d["model"], ""),
                        "supports": "",
                    },
                }
            )
            if d["offline"]:
                continue
            p = by.get(d["parent"])
            targets = [
                (
                    {"ieeeAddr": p["ieee"], "networkAddress": p["nwk"]} if p and not p["offline"] else root,
                    d["lqi"],
                    1 if not d["router"] else 2,
                )
            ]
            if d["router"] and p and d["lqi"] > 110:
                targets.append((root, d["lqi"] - 70, 2))
            for tgt, lqi, rel in targets:
                links.append(
                    {
                        "source": me,
                        "target": tgt,
                        "linkquality": lqi,
                        "lqi": lqi,
                        "depth": depth(d),
                        "routes": [],
                        "relationship": rel,
                        "sourceIeeeAddr": d["ieee"],
                        "targetIeeeAddr": tgt["ieeeAddr"],
                        "sourceNwkAddr": d["nwk"],
                    }
                )
        return {
            "type": req.get("type", "raw"),
            "routes": bool(req.get("routes")),
            "value": {"nodes": nodes, "links": links},
        }

    async def rq_device_ota_update_check(self, req: dict[str, Any]) -> dict[str, Any]:
        d = self.need(req)
        await asyncio.sleep(2)
        if d["offline"]:
            raise ValueError(f"Failed to check if update available for '{d['fn']}' (Timeout)")
        return {"id": req["id"], "update_available": bool(d["update"] and d["update"]["state"] == "available")}

    async def rq_device_ota_update_update(self, req: dict[str, Any]) -> dict[str, Any]:
        d = self.need(req)
        u = d["update"]
        if not u or u["state"] != "available":
            raise ValueError(f"Update of '{d['fn']}' failed (No new image available)")
        frm, to = u["installed_version"], u["latest_version"]
        log.info("ota %s %s -> %s", d["fn"], frm, to)
        for i in range(1, 21):
            d["update"] = {
                "state": "updating",
                "progress": i * 5.0,
                "remaining": (20 - i) * 3,
                "installed_version": frm,
                "latest_version": to,
            }
            await self.state(d)
            await asyncio.sleep(3 / max(SPEED, 1))
        d["sw"], d["update"] = to, {"state": "idle", "installed_version": to, "latest_version": to}
        self.save()
        await self.state(d)
        await self.bridge()
        return {"id": req["id"], "from": {"software_build_id": frm}, "to": {"software_build_id": to}}

    async def rq_device_remove(self, req: dict[str, Any]) -> dict[str, Any]:
        d = self.need(req)
        if d["offline"] and not req.get("force"):
            await asyncio.sleep(3)
            raise ValueError(f"Failed to remove device '{d['fn']}' (Timeout)")
        d["joined"] = False
        await self.pub(f"{Z}/{d['fn']}", "", True)
        await self.pub(f"{Z}/{d['fn']}/availability", "", True)
        await self.bridge()
        log.info("device %s removed", d["fn"])
        self.save()
        return {"id": req["id"], "block": bool(req.get("block")), "force": bool(req.get("force"))}

    async def rq_device_configure(self, req: dict[str, Any]) -> dict[str, Any]:
        d = self.need(req)
        await asyncio.sleep(1.5)
        if d["offline"]:
            raise ValueError(f"Failed to configure '{d['fn']}' (Timeout)")
        return {"id": req["id"]}

    async def rq_device_interview(self, req: dict[str, Any]) -> dict[str, Any]:
        d = self.need(req)
        data = {"friendly_name": d["fn"], "ieee_address": d["ieee"]}
        await self.pub(f"{Z}/bridge/event", {"type": "device_interview", "data": {**data, "status": "started"}})
        await asyncio.sleep(4)
        if d["offline"]:
            await self.pub(f"{Z}/bridge/event", {"type": "device_interview", "data": {**data, "status": "failed"}})
            raise ValueError(f"Failed to interview '{d['fn']}' (Timeout)")
        df = self.definition(d)
        await self.pub(
            f"{Z}/bridge/event",
            {
                "type": "device_interview",
                "data": {**data, "status": "successful", "supported": df is not None, "definition": df},
            },
        )
        return {"id": req["id"]}

    async def rq_backup(self, req: dict[str, Any]) -> dict[str, Any]:
        c, buf = self.sc["coordinator"], io.BytesIO()
        devs = self.active()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(
                "configuration.yaml",
                f"homeassistant:\n  enabled: false\nmqtt:\n  base_topic: {Z}\nserial:\n  port: {c['port']}\n"
                f"  adapter: ember\nadvanced:\n  channel: {self.channel}\n  pan_id: {c['pan']}\n",
            )
            zf.writestr(
                "coordinator_backup.json",
                json.dumps(
                    {
                        "metadata": {
                            "format": "zigpy/open-coordinator-backup",
                            "version": 1,
                            "source": "zigbee-herdsman@4.1.0",
                            "internal": {"date": datetime.now(UTC).isoformat()},
                        },
                        "coordinator_ieee": c["ieee"][2:],
                        "pan_id": f"{c['pan']:04x}",
                        "channel": c["channel"],
                        "devices": [
                            {
                                "ieee_address": d["ieee"][2:],
                                "nwk_address": f"{d['nwk']:04x}",
                                "is_child": not d["router"],
                            }
                            for d in devs
                        ],
                    },
                    indent=2,
                ),
            )
            zf.writestr(
                "database.db",
                "\n".join(
                    json.dumps(
                        {
                            "id": i + 2,
                            "type": "Router" if d["router"] else "EndDevice",
                            "ieeeAddr": d["ieee"],
                            "nwkAddr": d["nwk"],
                            "manufName": d["vendor"],
                            "modelId": d["model"],
                        }
                    )
                    for i, d in enumerate(devs)
                ),
            )
            zf.writestr("state.json", json.dumps({d["ieee"]: d["st"] for d in devs}))
        return {"zip": base64.b64encode(buf.getvalue()).decode()}

    async def rq_options(self, req: dict[str, Any]) -> dict[str, Any]:
        ch = ((req.get("options") or {}).get("advanced") or {}).get("channel")
        if ch and int(ch) != self.channel:
            self.channel, self.restart_required = int(ch), True
            self.save()
        await self.bridge(False)
        return {"restart_required": self.restart_required}

    async def converters_changed(self) -> None:
        self.save()
        await self.pub(f"{Z}/bridge/converters", [{"name": k, "code": v} for k, v in self.converters.items()], True)
        await self.bridge()
        for d in self.active():
            if d["model"] == "TS0601":
                await self.state(d)

    async def rq_converter_save(self, req: dict[str, Any]) -> dict[str, Any]:
        self.converters[str(req.get("name"))] = str(req.get("code") or "")
        await self.converters_changed()
        return {}

    async def rq_converter_remove(self, req: dict[str, Any]) -> dict[str, Any]:
        if self.converters.pop(str(req.get("name")), None) is None:
            raise ValueError(f"Converter '{req.get('name')}' does not exist")
        await self.converters_changed()
        return {}

    async def rq_health_check(self, req: dict[str, Any]) -> dict[str, Any]:
        return {"healthy": True}

    async def rq_restart(self, req: dict[str, Any]) -> dict[str, Any]:
        async def restart() -> None:
            await self.pub(f"{Z}/bridge/state", {"state": "offline"}, True)
            await asyncio.sleep(4)
            self.sc["coordinator"]["channel"], self.restart_required = self.channel, False
            self.save()
            await self.boot()

        self.spawn(restart())
        return {}

    async def on_set(self, fn: str, p: Any) -> None:
        d = self.find(fn)
        if d is None or not isinstance(p, dict):
            return
        if d["offline"]:
            await asyncio.sleep(2)
            await self.pub(
                f"{Z}/bridge/logging",
                {
                    "level": "error",
                    "message": f"Publish 'set' '{','.join(p)}' to '{fn}' failed: "
                    f"'Error: ZCL command {d['ieee']}/1 failed (Timeout)'",
                },
            )
            return
        st, k = d["st"], d["kind"]
        if k == "blind":
            if p.get("state") == "STOP":
                d["target"] = None
            elif (tgt := p.get("position", {"OPEN": 100, "CLOSE": 0}.get(str(p.get("state"))))) is not None:
                d["target"] = max(0, min(100, int(tgt)))
                self.spawn(self.move(d))
            return
        for key, v in p.items():
            if key not in WRITABLE[k]:
                continue
            if key == "state":
                st["state"] = ("OFF" if st.get("state") == "ON" else "ON") if v == "TOGGLE" else v
            elif key == "brightness":
                st["brightness"] = max(0, min(254, int(v)))
                if st["brightness"] and "state" not in p:
                    st["state"] = "ON"
            else:
                st[key] = v
        if k == "plug" and st.get("state") != "ON":
            st.update(power=0.0, current=0.0)
        await asyncio.sleep(0.25)
        await self.state(d)

    async def move(self, d: dict[str, Any]) -> None:
        if d.get("moving"):
            return
        d["moving"] = True
        try:
            while d.get("target") is not None and d["st"]["position"] != d["target"]:
                cur = d["st"]["position"]
                d["st"]["position"] = cur + max(-10, min(10, d["target"] - cur))
                await self.state(d)
                await asyncio.sleep(1)
            d["target"] = None
        finally:
            d["moving"] = False

    async def on_hub_set(self, key: str, p: Any) -> None:
        h = self.hub.get(key)
        if h is None or not isinstance(p, dict):
            return
        caps = {c["id"]: c for c in h["caps"]}
        req = p.get("values") or {}
        values = {k: v for k, v in req.items() if "w" in caps.get(k, {}).get("access", "")}
        bad = sorted(set(req) - set(values))
        h["st"].update(values)
        await asyncio.sleep(0.2)
        await self.pub(
            f"hub/v1/dev/{key}/ack",
            {
                "cmd": p.get("cmd"),
                "ok": not bad,
                "values": values,
                **({"error": f"read only {', '.join(bad)}"} if bad else {}),
            },
        )
        await self.pub(f"hub/v1/dev/{key}/state", h["st"], True)

    async def on_ctl(self, p: Any) -> None:
        if not isinstance(p, dict):
            return
        key, values = p.get("device"), p.get("state") or {}
        log.info("ctl %s", p)
        d = next((x for x in self.active() if key in (x["key"], x["fn"], x["ieee"])), None)
        if d:
            if "online" in p:
                d["offline"] = not p["online"]
                await self.avail(d)
            d["st"].update(z2m(d["kind"], values))
            if d["kind"] == "motion" and values.get("occ"):
                d["clear"] = time.time() + 90 / SPEED
            if d["kind"] in ("trv", "floor") and "t" in values:
                d["x"] = float(values["t"])
            if not d["offline"]:
                await self.state(d)
        elif key in self.hub:
            h = self.hub[key]
            h["st"].update(values)
            h["x"] = float(h["st"].get("t", h["x"]))
            if "online" in p:
                await self.pub(f"hub/v1/dev/{key}/avail", "online" if p["online"] else "offline", True)
            await self.pub(f"hub/v1/dev/{key}/state", h["st"], True)
        elif key == "tech-boiler":
            self.boiler.update({k: v for k, v in values.items() if k in ("on", "t")})
            if "online" in p:
                await self.pub(f"{BOILER}/status", "online" if p["online"] else "offline", True)
            await self.boiler_state()

    def hour(self) -> float:
        t = datetime.now(self.tz)
        return t.hour + t.minute / 60

    def lux(self, d: dict[str, Any], h: float) -> int:
        day = max(0.0, 260 * math.sin(math.pi * (h - 8.3) / 8.6)) if 8.3 < h < 16.9 else 0.0
        lit = any(
            x["room"] == d["room"] and x["kind"] in ("light_ct", "relay_light") and x["st"].get("state") == "ON"
            for x in self.active()
        )
        return max(0, round((day + (120 if lit else 2)) * random.uniform(0.9, 1.1)))

    def step(self, d: dict[str, Any], dt: float, h: float, now: float) -> bool:
        st, k, base, due = d["st"], d["kind"], d["base"], now >= d["next"]
        if k in ("clim", "air") and due:
            out = d["room"] in self.outdoor
            wave = math.sin(2 * math.pi * (h - (8 if out else 10)) / 24)
            st["temperature"] = round(base["t"] + (3.0 if out else 0.5) * wave + random.gauss(0, 0.05), 1)
            st["humidity"] = round(base["h"] - (6 if out else 2) * wave + random.gauss(0, 0.4), 1)
            if k == "air":
                st["pm25"] = max(1, round(base["pm25"] + random.gauss(0, 1.5)))
                st["voc_index"] = max(1, round(base["voc"] + random.gauss(0, 6)))
        elif k in ("trv", "floor"):
            sp = float(st.get("occupied_heating_setpoint", st.get("current_heating_setpoint", 20)))
            heat = d["x"] < sp - 0.2 or (st.get("running_state") == "heat" and d["x"] < sp + 0.2)
            d["x"] = (
                d["x"] + (0.0016 if k == "trv" else 0.0012) * dt
                if heat
                else max(16.0 if k == "trv" else 21.0, d["x"] - 0.0006 * dt)
            )
            st["local_temperature"], st["running_state"] = round(d["x"], 1), "heat" if heat else "idle"
            last = d["pub"]
            return (
                st["running_state"] != last.get("running_state")
                or abs(st["local_temperature"] - last.get("local_temperature", -99)) >= 0.3
            )
        elif k == "motion":
            if d.get("clear") and now >= d["clear"]:
                d["clear"], st["occupancy"] = None, False
                return True
            rate = (8 if d["room"] == "kitchen" else 4) if 7 <= h < 23 else 0.3
            if not st["occupancy"] and random.random() < rate * dt / 3600:
                st["occupancy"], st["illuminance"], d["clear"] = True, self.lux(d, h), now + 90 / SPEED
                door = next((x for x in self.active() if x["kind"] == "contact" and x["room"] == d["room"]), None)
                if door and random.random() < 0.25:
                    self.spawn(self.door(door))
                return True
            if due:
                st["illuminance"] = self.lux(d, h)
        elif k == "plug":
            w = float(st.get("power", 0))
            d["kwh"] += w * dt / 3.6e6
            st["energy"] = round(d["kwh"], 2)
            if st.get("state") != "ON":
                w = 0.0
            elif base.get("w", 0) < 10:
                if d.get("burst", 0) > now:
                    w = 1350 + random.gauss(0, 15)
                elif random.random() < dt / 1200:
                    d["burst"], w = now + 45 / SPEED, 1350.0
                else:
                    w = base["w"] + random.gauss(0, 0.2)
            elif due:
                w = max(5.0, base["w"] * random.uniform(0.75, 1.5))
            st["power"] = round(max(0.0, w), 1)
            st["voltage"] = round(230 + random.gauss(0, 0.8), 1)
            st["current"] = round(st["power"] / st["voltage"], 3)
            last = float(d["pub"].get("power", 0))
            return abs(st["power"] - last) > max(5.0, 0.1 * last)
        elif k == "remote" and d["model"] == "E2001/E2002" and random.random() < dt / 2400:
            self.spawn(
                self.press(d, random.choice(["brightness_move_up", "brightness_move_down", "arrow_right_click"]))
            )
        return False

    async def door(self, d: dict[str, Any]) -> None:
        d["st"]["contact"] = False
        await self.state(d)
        await asyncio.sleep(random.uniform(8, 20) / SPEED)
        d["st"]["contact"] = True
        await self.state(d)

    async def press(self, d: dict[str, Any], action: str) -> None:
        await self.state(d, action=action)
        if action.endswith(("_up", "_down")):
            await asyncio.sleep(1.2)
            await self.state(d, action="brightness_stop")

    def load(self) -> float:
        w = 380 + 120 * math.sin(time.time() / 900) + random.gauss(0, 25)
        for d in self.active():
            st, k = d["st"], d["kind"]
            if d["offline"]:
                continue
            if k in ("light_ct", "relay_light", "relay") and st.get("state") == "ON":
                w += {"light_ct": 9, "relay_light": 40, "relay": 35}[k]
            elif k == "plug":
                w += float(st.get("power", 0))
            elif k == "floor" and st.get("running_state") == "heat" and self.supported(d):
                w += 850
        return w + 6000 * sum(1 for x in self.hub.values() if x.get("heating")) + self.boiler["w"]

    async def hub_step(self, dt: float, now: float) -> None:
        for h in self.hub.values():
            st = h["st"]
            if h["kind"] == "sauna":
                heating = bool(st.get("on")) and (
                    h["x"] < st["target"] - 1.5 or (h.get("heating") and h["x"] < st["target"])
                )
                h["heating"] = heating
                h["x"] = max(21.0, h["x"] + (0.02 if heating else -(0.004 if st.get("on") else 0.008)) * dt)
                st["t"] = round(h["x"], 1)
            elif h["kind"] == "meter":
                w = self.load()
                st["kwh"] = round(float(st.get("kwh", 0)) + float(st.get("w", 0)) * dt / 3.6e6, 3)
                st.update(w=round(w), v=round(230 + random.gauss(0, 1.2), 1))
            if now >= h["next"] or (h["kind"] == "sauna" and abs(st["t"] - h.get("pubt", -99)) >= 1):
                h["next"], h["pubt"] = now + (15 if h["kind"] == "meter" else 30) / SPEED, st.get("t")
                await self.pub(f"hub/v1/dev/{h['key']}/state", st, True)

    async def boiler_step(self, dt: float, now: float) -> None:
        bo = self.boiler
        heating = bo["on"] and bo["t"] < 80
        bo["t"] = bo["t"] + 0.008 * dt if heating else max(25.0, bo["t"] - 0.0008 * dt)
        w = 2000 + random.gauss(0, 12) if heating else 0.0
        changed, bo["w"] = (w > 0) != (bo["w"] > 0), w
        if changed or now >= bo["next"]:
            bo["next"] = now + 30 / SPEED
            await self.boiler_state()
        if now >= self.garage_next:
            self.garage_next = now + 60 / SPEED
            out = next(
                (
                    d["st"].get("temperature")
                    for d in self.active()
                    if d["room"] in self.outdoor and "temperature" in d["st"]
                ),
                3.0,
            )
            body = {
                "Time": datetime.now(self.tz).strftime("%Y-%m-%dT%H:%M:%S"),
                "DS18B20": {"Id": "3C01D607A3E1", "Temperature": round(out + 4 + random.gauss(0, 0.1), 1)},
                "TempUnit": "C",
            }
            await self.pub("garage/sensor/tele", body)

    async def loop(self) -> None:
        last = time.time()
        while True:
            await asyncio.sleep(5)
            now = time.time()
            dt, last, h = (now - last) * SPEED, now, self.hour()
            try:
                for d in self.active():
                    if not d["offline"] and (self.step(d, dt, h, now) or now >= d["next"]):
                        d["next"] = now + PERIOD.get(d["kind"], 3000) * random.uniform(0.8, 1.2) / SPEED
                        await self.state(d)
                await self.hub_step(dt, now)
                await self.boiler_step(dt, now)
            except aiomqtt.MqttError:
                raise
            except Exception:
                log.exception("tick failed")

    async def dispatch(self, m: aiomqtt.Message) -> None:
        t = m.topic.value
        raw = m.payload.decode(errors="replace") if isinstance(m.payload, (bytes, bytearray)) else str(m.payload or "")
        try:
            p = json.loads(raw) if raw else {}
        except ValueError:
            p = raw
        if t.startswith(f"{Z}/bridge/request/"):
            self.spawn(self.on_request(t[len(Z) + 16 :], p))
        elif t.startswith(f"{Z}/") and t.endswith("/set"):
            self.spawn(self.on_set(t[len(Z) + 1 : -4], p))
        elif t.startswith(f"{Z}/") and t.endswith("/get") and (d := self.find(t[len(Z) + 1 : -4])):
            self.spawn(self.state(d))
        elif t.startswith("hub/v1/dev/") and t.endswith("/set"):
            self.spawn(self.on_hub_set(t.split("/")[3], p))
        elif t == f"{BOILER}/switch/relay/command":
            self.boiler["on"] = raw.strip().upper() == "ON"
            self.boiler["next"] = 0.0
            self.spawn(self.boiler_state())
        elif t == CTL:
            self.spawn(self.on_ctl(p))

    async def run(self) -> None:
        will = aiomqtt.Will(f"{Z}/bridge/state", json.dumps({"state": "offline"}), qos=1, retain=True)
        while True:
            try:
                async with client(will=will) as c:
                    self.c = c
                    for topic in (
                        f"{Z}/bridge/request/#",
                        f"{Z}/+/set",
                        f"{Z}/+/get",
                        "hub/v1/dev/+/set",
                        f"{BOILER}/switch/relay/command",
                        CTL,
                    ):
                        await c.subscribe(topic, qos=1)
                    await self.boot()
                    log.info("simulator ready, %s zigbee devices, speed %s", len(self.active()), SPEED)
                    ticker = asyncio.ensure_future(self.loop())
                    try:
                        async for m in c.messages:
                            await self.dispatch(m)
                    finally:
                        ticker.cancel()
            except aiomqtt.MqttError as e:
                log.warning("mqtt unavailable (%s), retry in 3s", e)
                await asyncio.sleep(3)
