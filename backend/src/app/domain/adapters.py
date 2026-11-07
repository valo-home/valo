import re
from typing import Any

from app.domain.common import slug
from app.lib.errors import ApplicationError

KEYS = {
    "state": "on",
    "brightness": "bri",
    "color_temp": "ct",
    "temperature": "t",
    "local_temperature": "t",
    "humidity": "h",
    "illuminance": "lux",
    "illuminance_lux": "lux",
    "occupancy": "occ",
    "presence": "occ",
    "contact": "open",
    "water_leak": "leak",
    "smoke": "smoke",
    "carbon_monoxide": "co",
    "gas": "gas",
    "battery": "bat",
    "power": "w",
    "energy": "kwh",
    "voltage": "v",
    "current": "a",
    "linkquality": "lqi",
    "occupied_heating_setpoint": "sp",
    "current_heating_setpoint": "sp",
    "position": "pos",
    "running_state": "heat",
    "pressure": "pa",
    "co2": "co2",
    "pm25": "pm25",
    "voc": "voc",
    "action": "action",
    "tamper": "tamper",
    "battery_low": "batlow",
    "system_mode": "mode",
    "child_lock": "lock",
}
UNITS = {
    "t": "°C",
    "h": "%",
    "lux": "lx",
    "bat": "%",
    "w": "W",
    "kwh": "kWh",
    "v": "V",
    "a": "A",
    "sp": "°C",
    "pos": "%",
    "bri": "%",
    "ct": "K",
    "pa": "hPa",
    "co2": "ppm",
}
LOGGED = {"on", "open", "leak", "occ", "smoke", "co", "gas", "action", "heat", "tamper", "lock", "mode", "smoke_state"}
ALARMS = {"leak": "leak", "smoke": "smoke", "co": "co", "gas": "gas"}
HA_CLASS = {
    "temperature": "t",
    "humidity": "h",
    "illuminance": "lux",
    "power": "w",
    "energy": "kwh",
    "voltage": "v",
    "current": "a",
    "battery": "bat",
    "pressure": "pa",
    "carbon_dioxide": "co2",
    "pm25": "pm25",
    "door": "open",
    "window": "open",
    "opening": "open",
    "garage_door": "open",
    "moisture": "leak",
    "motion": "occ",
    "occupancy": "occ",
    "presence": "occ",
    "smoke": "smoke",
    "carbon_monoxide": "co",
    "gas": "gas",
}
HA_ABBR = {
    "stat_t": "state_topic",
    "cmd_t": "command_topic",
    "val_tpl": "value_template",
    "dev": "device",
    "ids": "identifiers",
    "mf": "manufacturer",
    "mdl": "model",
    "uniq_id": "unique_id",
    "obj_id": "object_id",
    "dev_cla": "device_class",
    "unit_of_meas": "unit_of_measurement",
    "pl_on": "payload_on",
    "pl_off": "payload_off",
    "stat_on": "state_on",
    "stat_off": "state_off",
    "avty_t": "availability_topic",
    "pl_avail": "payload_available",
    "pl_not_avail": "payload_not_available",
    "pos_t": "position_topic",
    "set_pos_t": "set_position_topic",
    "ops": "options",
    "p": "platform",
    "cmps": "components",
    "o": "origin",
    "sw": "sw_version",
    "stat_cla": "state_class",
}
_TPL = re.compile(
    r"\{\{\s*(value_json(?:\.\w+|\[['\"][^'\"]+['\"]\]|\[\d+\])*|value)\s*(?:\|\s*(\w+)(?:\(([^)]*)\))?\s*)?\}\}"
)
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
_SEG = re.compile(r"\.(\w+)|\[['\"]([^'\"]+)['\"]\]|\[(\d+)\]")


def kind_of(caps: list[dict[str, Any]], hint: str | None = None) -> str:
    if hint:
        return hint
    ids = {c["id"] for c in caps}
    for k, test in (
        ("lock", {"locked"}),
        ("light", {"bri", "ct", "color"}),
        ("fan", {"fan_mode"}),
        ("trv", {"sp"}),
        ("blind", {"pos"}),
        ("leak", {"leak"}),
        ("smoke", {"smoke", "co", "gas"}),
        ("motion", {"occ"}),
        ("contact", {"open"}),
    ):
        if ids & test:
            return k
    if "on" in ids or any(i.startswith("on_") for i in ids):
        return "plug" if ids & {"w", "kwh"} else "switch"
    if ids & {"w", "kwh"}:
        return "meter"
    if "t" in ids:
        return "clim"
    return "button" if "action" in ids else "other"


def validate(cap: dict[str, Any], value: Any) -> Any:
    t, cid = cap.get("type"), cap["id"]
    if "w" not in cap.get("access", "r"):
        raise ApplicationError("cap_not_writable", 422, cap=cid)
    if t == "bool" and isinstance(value, bool):
        return value
    if t == "num" and isinstance(value, (int, float)) and not isinstance(value, bool):
        lo, hi, step = cap.get("min"), cap.get("max"), cap.get("step")
        if (lo is not None and value < lo) or (hi is not None and value > hi):
            raise ApplicationError("value_invalid", 422, cap=cid)
        return round(round(value / step) * step, 4) if step else value
    if t == "enum" and value in cap.get("values", []):
        return value
    if t == "text" and isinstance(value, str):
        return value
    if t == "color" and isinstance(value, str) and _HEX.match(value):
        return value.lower()
    raise ApplicationError("value_invalid", 422, cap=cid)


def z2m_caps(exposes: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    caps, conv = [], {}

    def add(e: dict[str, Any], parent: str | None) -> None:
        prop, typ = e.get("property"), e.get("type")
        a = e.get("access", 1)
        access = ("r" if a & 1 else "") + ("w" if a & 2 else "") or "r"
        if typ == "composite" and prop == "color" and "color" not in conv:
            caps.append({"id": "color", "type": "color", "access": access})
            conv["color"] = {"p": "color", "color": "hs" if e.get("name") == "color_hs" else "xy"}
            return
        if not prop or typ not in ("binary", "numeric", "enum", "text"):
            return
        ep = e.get("endpoint")
        base = prop[: -len(ep) - 1] if ep and prop.endswith(f"_{ep}") else prop
        if parent == "cover" and base == "state":
            key = "move"
        elif parent == "lock" and base == "state":
            key = "locked"
        elif parent == "fan" and base == "mode":
            key = "fan_mode"
        else:
            key = KEYS.get(base, base)
        if ep and base != prop:
            key = f"{key}_{ep}"
        if key in conv:
            key = prop
        cap: dict[str, Any] = {
            "id": key,
            "type": {"binary": "bool", "numeric": "num", "enum": "enum"}.get(typ, "text"),
            "access": access,
        }
        c: dict[str, Any] = {"p": prop}
        if typ == "binary":
            c.update(on=e.get("value_on", True), off=e.get("value_off", False), inv=base == "contact")
        elif typ == "numeric":
            cap.update(
                {
                    k2: e[k1]
                    for k1, k2 in (("value_min", "min"), ("value_max", "max"), ("value_step", "step"))
                    if k1 in e
                }
            )
            if base == "brightness":
                c["scale"] = e.get("value_max", 254)
                cap.update(min=0, max=100, step=1)
            elif base == "color_temp":
                c["mired"] = True
                cap.update(min=round(1e6 / e.get("value_max", 500)), max=round(1e6 / e.get("value_min", 153)), step=50)
            cap["unit"] = UNITS.get(key) or e.get("unit")
        elif typ == "enum":
            cap["values"] = e.get("values", [])
            if base == "running_state":
                cap = {"id": key, "type": "bool", "access": "r"}
                c["heat"] = "heat"
        caps.append(cap)
        conv[key] = c

    def walk(items: list[dict[str, Any]], parent: str | None = None) -> None:
        for e in items:
            if e.get("features") and e.get("type") in ("light", "switch", "climate", "cover", "lock", "fan"):
                walk(e["features"], e.get("type"))
            else:
                add(e, parent)

    walk(exposes)
    return caps, conv


def z2m_in(conv: dict[str, dict[str, Any]], payload: dict[str, Any]) -> dict[str, Any]:
    values = {}
    for key, c in conv.items():
        if c["p"] not in payload:
            continue
        v = payload[c["p"]]
        if v is None:
            continue
        if "color" in c:
            v = color_hex(v, payload.get("brightness"))
        elif "on" in c:
            v = v == c["on"]
            v = not v if c.get("inv") else v
        elif "scale" in c:
            v = round(v * 100 / c["scale"])
        elif c.get("mired"):
            v = round(1e6 / v) if v else None
        elif "heat" in c:
            v = v == c["heat"]
        values[key] = v
    return values


def _hex(r: float, g: float, b: float) -> str:
    return "#" + "".join(f"{max(0, min(255, round(x * 255))):02x}" for x in (r, g, b))


def color_hex(v: Any, _brightness: Any = None) -> str | None:
    if isinstance(v, str):
        return v.lower() if _HEX.match(v) else None
    if not isinstance(v, dict):
        return None
    if isinstance(v.get("hex"), str) and _HEX.match(v["hex"]):
        return v["hex"].lower()
    if v.get("x") is not None and v.get("y") is not None:
        x, y = float(v["x"]), float(v["y"])
        if y <= 0:
            return None
        z = 1.0 - x - y
        big_x, big_z = x / y, z / y
        r = big_x * 1.656492 - 0.354851 - big_z * 0.255038
        g = -big_x * 0.707196 + 1.655397 + big_z * 0.036152
        b = big_x * 0.051713 - 0.121364 + big_z * 1.011530
        r, g, b = (12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055 for c in (r, g, b))
        m = max(r, g, b, 1e-9)
        return _hex(*(max(0.0, c) / m for c in (r, g, b)))
    if v.get("hue") is not None:
        h, sat = float(v["hue"]) % 360 / 60, float(v.get("saturation", 100)) / 100
        i, f = int(h), h - int(h)
        p, q, t = 1 - sat, 1 - sat * f, 1 - sat * (1 - f)
        return _hex(*[(1, t, p), (q, 1, p), (p, 1, t), (p, q, 1), (t, p, 1), (1, p, q)][i % 6])
    return None


def z2m_out(conv: dict[str, dict[str, Any]], values: dict[str, Any]) -> dict[str, Any]:
    payload = {}
    for key, v in values.items():
        c = conv.get(key)
        if c is None:
            raise ApplicationError("cap_unknown", 422, cap=key)
        if "color" in c:
            v = {"hex": v}
        elif "on" in c:
            v = c["on"] if (not v if c.get("inv") else v) else c["off"]
        elif "scale" in c:
            v = round(v * c["scale"] / 100)
        elif c.get("mired"):
            v = round(1e6 / v)
        payload[c["p"]] = v
    return payload


def ha_expand(cfg: Any, base: str | None = None) -> Any:
    if isinstance(cfg, dict):
        base = cfg.get("~", base)
        out = {}
        for k, v in cfg.items():
            if k == "~":
                continue
            k = HA_ABBR.get(k, k)
            v = ha_expand(v, base)
            if base and isinstance(v, str) and k.endswith("topic"):
                v = base + v[1:] if v.startswith("~") else v[:-1] + base if v.endswith("~") else v
            out[k] = v
        return out
    if isinstance(cfg, list):
        return [ha_expand(x, base) for x in cfg]
    return cfg


def ha_components(topic: str, cfg: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    parts = topic.split("/")
    cfg = ha_expand(cfg)
    if parts[1] == "device":
        shared = {k: v for k, v in cfg.items() if k not in ("components", "device", "origin")}
        return [
            (c.get("platform", ""), cid, {**shared, **c, "device": cfg.get("device", {})})
            for cid, c in (cfg.get("components") or {}).items()
        ]
    return [(parts[1], parts[-2], cfg)]


def ha_cap(platform: str, oid: str, c: dict[str, Any], taken: set[str]) -> tuple[dict[str, Any], dict[str, Any]] | None:
    if platform not in ("sensor", "binary_sensor", "switch", "light", "number", "select", "cover", "button"):
        return None
    key = (
        {"switch": "on", "light": "on", "cover": "pos"}.get(platform)
        or HA_CLASS.get(c.get("device_class", ""))
        or slug(c.get("name") or oid, oid)
    )
    if key in taken:
        key = slug(oid, oid)
    typ = {
        "binary_sensor": "bool",
        "switch": "bool",
        "light": "bool",
        "number": "num",
        "cover": "num",
        "select": "enum",
        "button": "bool",
    }.get(platform) or ("num" if c.get("unit_of_measurement") else "text")
    cmd = c.get("set_position_topic") or c.get("command_topic")
    access = ("" if platform == "button" else "r") + ("w" if cmd else "")
    cap = {"id": key, "type": typ, "access": access or "r", "name": c.get("name") or oid}
    if c.get("unit_of_measurement"):
        cap["unit"] = c["unit_of_measurement"]
    cap.update({k: c[k] for k in ("min", "max", "step") if k in c})
    if typ == "enum":
        cap["values"] = c.get("options", [])
    if platform == "cover":
        cap.update(min=0, max=100, unit="%")
    on = c.get("state_on", c.get("payload_on", "ON"))
    conv = {
        "st": c.get("position_topic") if platform == "cover" else c.get("state_topic"),
        "tpl": c.get("value_template"),
        "cmd": cmd,
        "on": on,
        "off": c.get("state_off", c.get("payload_off", "OFF")),
        "pon": c.get("payload_on", on),
        "poff": c.get("payload_off", "OFF"),
        "press": c.get("payload_press", "PRESS"),
        "button": platform == "button",
        "avail": c.get("availability_topic"),
        "aon": c.get("payload_available", "online"),
        "aoff": c.get("payload_not_available", "offline"),
    }
    return cap, conv


def render(tpl: str | None, raw: Any) -> Any:
    if not tpl:
        return raw
    m = _TPL.fullmatch(tpl.strip())
    if not m:
        return raw
    path, flt, arg = m.groups()
    v = raw
    if path != "value":
        if not isinstance(raw, (dict, list)):
            return None
        for a, b, i in _SEG.findall(path[len("value_json") :]):
            try:
                v = v[int(i)] if i else v[a or b]
            except KeyError, IndexError, TypeError:
                return None
    try:
        if flt == "float":
            v = float(v)
        elif flt == "int":
            v = int(float(v))
        elif flt == "round":
            v = round(float(v), int(arg or 0))
        elif flt in ("lower", "upper"):
            v = getattr(str(v), flt)()
    except TypeError, ValueError:
        return None
    return v


def cast(cap: dict[str, Any], v: Any, on: Any = "ON", off: Any = "OFF") -> Any:
    t = cap.get("type")
    if t == "bool":
        if isinstance(v, bool):
            return v
        s = str(v)
        return (
            True
            if s == str(on) or s.lower() in ("true", "1", "on", "open")
            else False
            if s == str(off) or s.lower() in ("false", "0", "off", "closed")
            else None
        )
    if t == "num":
        try:
            return float(v) if "." in str(v) else int(v)
        except TypeError, ValueError:
            return None
    return v


def ha_in(caps: list[dict[str, Any]], conv: dict[str, dict[str, Any]], topic: str, payload: Any) -> dict[str, Any]:
    values = {}
    for cap in caps:
        c = conv.get(cap["id"])
        if not c or c.get("st") != topic:
            continue
        v = cast(cap, render(c.get("tpl"), payload), c.get("on"), c.get("off"))
        if v is not None:
            values[cap["id"]] = v
    return values


def ha_out(conv: dict[str, dict[str, Any]], values: dict[str, Any]) -> list[tuple[str, Any]]:
    msgs = []
    for k, v in values.items():
        c = conv.get(k) or {}
        if not c.get("cmd"):
            raise ApplicationError("cap_not_writable", 422, cap=k)
        msgs.append(
            (
                c["cmd"],
                c["press"] if c.get("button") else (c["pon"] if v else c["poff"]) if isinstance(v, bool) else str(v),
            )
        )
    return msgs


def pick(payload: Any, path: str) -> Any:
    v = payload
    for part in [p for p in path.split(".") if p] if path else []:
        if isinstance(v, dict):
            v = v.get(part)
        elif isinstance(v, list) and part.isdigit() and int(part) < len(v):
            v = v[int(part)]
        else:
            return None
    return v


def map_in(rows: list[dict[str, Any]], topic: str, payload: Any) -> dict[str, Any]:
    values = {}
    for r in rows:
        if r.get("topic") == topic:
            v = cast(r, pick(payload, r.get("path", "")), r.get("on", "ON"), r.get("off", "OFF"))
            if v is not None:
                values[r["id"]] = v
    return values


def map_out(rows: list[dict[str, Any]], values: dict[str, Any]) -> list[tuple[str, Any]]:
    by = {r["id"]: r for r in rows}
    msgs = []
    for k, v in values.items():
        r = by.get(k)
        if not r or not r.get("cmd"):
            raise ApplicationError("cap_not_writable", 422, cap=k)
        if isinstance(v, bool):
            v = r.get("on", "ON") if v else r.get("off", "OFF")
        msgs.append((r["cmd"], (r.get("tpl") or "{value}").replace("{value}", str(v))))
    return msgs


def hub_caps(meta: dict[str, Any]) -> list[dict[str, Any]]:
    caps = []
    for c in meta.get("caps") or []:
        if not isinstance(c, dict) or not c.get("id"):
            continue
        cap = {"id": str(c["id"]), "type": c.get("type", "num"), "access": c.get("access", "r").replace("s", "")}
        cap.update({k: c[k] for k in ("unit", "min", "max", "step", "values", "name") if k in c})
        if not cap.get("unit") and cap["id"] in UNITS:
            cap["unit"] = UNITS[cap["id"]]
        caps.append(cap)
    return caps
