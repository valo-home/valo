import json
import re
from typing import Any
from urllib.parse import urlencode

from valo_camera import CameraError, rtsp_check, with_auth

TIMEOUT = 8
POOL = "pool.ntp.org"
__all__ = ["CameraError", "rtsp_check"]


class Unsupported(Exception):
    """Прошивка не отдает поток событий, нужен опрос состояния."""


def host_of(cfg: dict[str, Any]) -> str:
    h = str(cfg.get("host") or "").strip()
    h = re.sub(r"^[a-z]+://", "", h).split("/")[0]
    if not h or not re.match(r"^[A-Za-z0-9.\-:\[\]]+$", h):
        raise CameraError("camera address is empty or invalid")
    return h


def api_url(cfg: dict[str, Any], path: str, **params: Any) -> str:
    q = {**params, "token": str(cfg.get("token") or "")}
    return f"http://{host_of(cfg)}{path}?{urlencode(q)}"


def agent_url(cfg: dict[str, Any], agent_path: str) -> str:
    return api_url(cfg, "/x/agent.cgi", agent_path=agent_path)


def rtsp_url(cfg: dict[str, Any], channel: str) -> str:
    path = str(channel or "").strip("/") or "ch0"
    return with_auth(
        f"rtsp://{host_of(cfg)}/{path}", str(cfg.get("user") or "thingino"), str(cfg.get("password") or "")
    )


def stills(cfg: dict[str, Any]) -> dict[str, str]:
    if not cfg.get("token"):
        return {}
    main = str(cfg.get("main") or "ch0").strip("/")
    sub = str(cfg.get("sub", "ch1") or main).strip("/")
    return {"snapshot": api_url(cfg, f"/x/{main}.jpg"), "preview": api_url(cfg, f"/x/{sub}.jpg")}


def info_of(device: Any) -> dict[str, Any]:
    d = device if isinstance(device, dict) else {}
    sw = d.get("software") if isinstance(d.get("software"), dict) else {}
    return {
        "vendor": "Thingino",
        "model": str(d.get("model") or "Thingino"),
        "hostname": str(d.get("hostname") or d.get("name") or ""),
        "mac": str(d.get("id") or ""),
        "firmware": str(sw.get("firmware_version") or ""),
    }


class Sse:
    """Разбор потока Server-Sent Events построчно."""

    def __init__(self) -> None:
        self.event = ""
        self.data: list[str] = []

    def feed(self, line: str) -> tuple[str, Any] | None:
        line = line.rstrip("\r\n")
        if line == "":
            if not self.event and not self.data:
                return None
            raw = "\n".join(self.data)
            ev, self.event, self.data = self.event, "", []
            try:
                body: Any = json.loads(raw) if raw else {}
            except ValueError:
                body = raw
            if not ev and isinstance(body, dict):
                ev = str(body.get("type") or "")
            return ev, body
        if line.startswith(":"):
            return None
        key, _, value = line.partition(":")
        value = value[1:] if value.startswith(" ") else value
        if key == "event":
            self.event = value
        elif key == "data":
            self.data.append(value)
        return None


def motion_of(event: str, body: Any) -> bool | None:
    name = event or (body.get("type") if isinstance(body, dict) else "")
    if name in ("motion.started", "motion.start", "motion"):
        if isinstance(body, dict) and isinstance(body.get("active"), bool):
            return body["active"]
        return True
    if name in ("motion.stopped", "motion.stop", "motion.ended"):
        return False
    return None


def sse_error(line: str) -> bool:
    """Агент без потока событий отвечает 200 и JSON с ошибкой вместо событий."""
    try:
        body = json.loads(line)
    except ValueError:
        return False
    return isinstance(body, dict) and body.get("status") == "error"


FLICKER = {0: "off", 1: "50", 2: "60"}
DAYNIGHT = ("auto", "day", "night")
IMAGE = ("brightness", "contrast", "saturation", "sharpness")
FLIPS = ("hflip", "vflip")
STREAMS = {"main": 0, "sub": 1}
JOG = 0.25


def _dig(d: Any, *keys: Any) -> Any:
    for k in keys:
        if isinstance(d, dict):
            d = d.get(k)
        elif isinstance(d, list) and isinstance(k, int) and 0 <= k < len(d):
            d = d[k]
        else:
            return None
    return d


def _can(schema: Any, *path: str) -> bool:
    return isinstance(_dig(schema, "settings", *path), dict)


def _int(v: Any, lo: int, hi: int) -> int:
    if isinstance(v, bool):
        raise CameraError("value must be a number")
    try:
        n = int(float(v))
    except (TypeError, ValueError) as e:
        raise CameraError("value must be a number") from e
    if not lo <= n <= hi:
        raise CameraError(f"value must be from {lo} to {hi}")
    return n


def _bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if v in (0, 1, "0", "1", "true", "false"):
        return v in (1, "1", "true")
    raise CameraError("value must be on or off")


def daynight_of(doc: Any, hb: Any) -> str:
    if _dig(doc, "daynight", "enabled"):
        return "auto"
    mode = _dig(doc, "daynight", "force_mode") or _dig(hb, "daynight_mode") or "day"
    return mode if mode in DAYNIGHT else "day"


def fields_of(doc: Any, hb: Any, schema: Any, tm: Any, now: float) -> list[dict[str, Any]]:
    """Описание настроек камеры для формы Valo по конфигурации агента, пульсу и схеме прошивки."""
    raw = _dig(doc, "backend", "raw") or {}
    out: list[dict[str, Any]] = []

    def add(key: str, section: str, kind: str, value: Any, writable: bool, **extra: Any) -> None:
        if value is None and kind != "info":
            return
        f = {"key": key, "section": section, "type": kind, "value": value, **extra}
        if not writable:
            f["readonly"] = True
        out.append(f)

    add("motion_enabled", "motion", "bool", _dig(doc, "motion", "enabled"), _can(schema, "motion", "enabled"))
    add(
        "motion_sensitivity",
        "motion",
        "int",
        _dig(raw, "motion", "sensitivity"),
        _can(schema, "motion", "sensitivity"),
        min=1,
        max=8,
        step=1,
    )
    add(
        "motion_cooldown",
        "motion",
        "int",
        _dig(raw, "motion", "cooldown_time"),
        _can(schema, "motion", "cooldown_time"),
        min=1,
        max=60,
        step=1,
        unit="s",
    )
    if _dig(doc, "daynight") is not None:
        add(
            "daynight_mode",
            "daynight",
            "select",
            daynight_of(doc, hb),
            _can(schema, "daynight", "enabled"),
            options=list(DAYNIGHT),
        )
    if _dig(hb, "daynight_mode") is not None:
        add("daynight_now", "daynight", "info", _dig(hb, "daynight_mode"), False)
    ir = _dig(hb, "ir940_state") if _dig(hb, "ir940_state") is not None else _dig(hb, "ir850_state")
    if ir is not None:
        add("ir_light", "daynight", "info", "on" if ir else "off", False)
    add("privacy", "privacy", "bool", _dig(doc, "privacy", "enabled"), _can(schema, "privacy", "enabled"))
    for k in IMAGE:
        add(k, "image", "int", _dig(doc, "image", k), _can(schema, "image", k), min=0, max=255, step=1)
    fl = _dig(doc, "image", "anti_flicker")
    if fl is not None:
        add(
            "anti_flicker",
            "image",
            "select",
            FLICKER.get(fl, "off"),
            _can(schema, "image", "anti_flicker"),
            options=list(FLICKER.values()),
        )
    for k in FLIPS:
        add(k, "image", "bool", _dig(doc, "image", k), _can(schema, "image", k))
    mic = _dig(hb, "mic_enabled")
    add("mic_enabled", "audio", "bool", bool(mic) if mic is not None else None, _can(schema, "audio", "mic_enabled"))
    for name, i in STREAMS.items():
        st = _dig(doc, "streams", i)
        if not isinstance(st, dict):
            continue
        w, h = st.get("width"), st.get("height")
        if w and h:
            add(f"{name}_size", "streams", "info", f"{w}x{h} {st.get('format') or ''}".strip(), False)
        can = isinstance(_dig(schema, "settings", "streams", "properties", "fps"), dict)
        add(f"{name}_fps", "streams", "int", st.get("fps"), can, min=5, max=30, step=1, unit="fps", restart=True)
        add(
            f"{name}_bitrate",
            "streams",
            "int",
            st.get("bitrate"),
            can,
            min=200,
            max=8000,
            step=100,
            unit="kbps",
            restart=True,
        )
    if isinstance(tm, dict):
        add("timezone", "time", "info", tm.get("tz_name") or "", False)
        add("ntp", "time", "info", tm.get("ntp_server_0") or "", False)
    ts = _dig(hb, "time_now")
    if isinstance(ts, (int, float)):
        add("clock_drift", "time", "info", round(ts - now), False, unit="s")
    return out


def patch_of(key: str, value: Any, schema: Any) -> list[tuple[str, str, dict[str, Any]]]:
    """Запросы к агенту для одной настройки: [(метод, путь агента, тело)]. Неверное значение дает CameraError."""
    s = "/api/v1/settings"
    if key == "motion_enabled":
        return [("PATCH", f"{s}/motion/enabled", {"enabled": _bool(value)})]
    if key == "motion_sensitivity":
        return [("PATCH", f"{s}/motion/sensitivity", {"sensitivity": _int(value, 1, 8)})]
    if key == "motion_cooldown":
        return [("PATCH", f"{s}/motion/cooldown-time", {"cooldown_time": _int(value, 1, 60)})]
    if key == "daynight_mode":
        if value not in DAYNIGHT:
            raise CameraError("mode must be auto, day or night")
        if value == "auto":
            return [("PATCH", f"{s}/daynight/enabled", {"enabled": True})]
        return [
            ("PATCH", f"{s}/daynight/enabled", {"enabled": False}),
            ("PATCH", f"{s}/daynight/force-mode", {"force_mode": value}),
        ]
    if key == "privacy":
        return [("PATCH", f"{s}/privacy/enabled", {"enabled": _bool(value)})]
    if key in IMAGE:
        return [("PATCH", f"{s}/image/{key}", {key: _int(value, 0, 255)})]
    if key == "anti_flicker":
        code = next((k for k, v in FLICKER.items() if v == str(value)), None)
        if code is None:
            raise CameraError("anti flicker must be off, 50 or 60")
        return [("PATCH", f"{s}/image/anti-flicker", {"anti_flicker": code})]
    if key in FLIPS:
        return [("PATCH", f"{s}/image/{key}", {key: _bool(value)})]
    if key == "mic_enabled":
        if not _can(schema, "audio", "mic_enabled"):
            raise CameraError("this firmware cannot switch the microphone")
        return [("PATCH", f"{s}/audio/mic-enabled", {"mic_enabled": _bool(value)})]
    name, _, prop = key.partition("_")
    if name in STREAMS and prop in ("fps", "bitrate"):
        n = _int(value, 5, 30) if prop == "fps" else _int(value, 200, 8000)
        return [("PATCH", f"{s}/streams/{STREAMS[name]}/{prop}", {prop: n})]
    raise CameraError(f"setting {key} is not supported")


def accepted(body: Any) -> bool:
    return isinstance(body, dict) and body.get("status") in ("accepted", "ok", None) and "error" not in body


def subnet_hosts(host: str) -> list[str]:
    """Адреса сети /24 вокруг прежнего адреса камеры."""
    ip = host.split(":")[0]
    parts = ip.split(".")
    if len(parts) != 4 or not all(p.isdigit() and 0 <= int(p) <= 255 for p in parts):
        return []
    base = ".".join(parts[:3])
    return [f"{base}.{i}" for i in range(1, 255)]


def is_thingino(page: bytes) -> bool:
    low = page[:4096].lower()
    return b"<title>thingino" in low or b"thingino" in low[:2048]


def same_camera(device: Any, mac: str) -> bool:
    got = str(_dig(device, "id") or "").lower().replace(":", "")
    return bool(mac) and got == mac.lower().replace(":", "")


def motor_status(body: Any) -> dict[str, Any] | None:
    """Ответ json-motor.cgi d=j: положение моторов или None, если моторов нет."""
    msg = _dig(body, "message")
    if not isinstance(msg, dict) or "xpos" not in msg:
        return None
    try:
        return {"x": int(msg["xpos"]), "y": int(msg.get("ypos", 0))}
    except TypeError, ValueError:
        return None


def streamer_running(health: Any) -> bool | None:
    """Работает ли видеосервис по ответу /api/v1/health агента."""
    for path in (("checks", "streaming", "running"), ("checks", "system", "streamer_running")):
        v = _dig(health, *path)
        if isinstance(v, bool):
            return v
    return None


def motor_busy(body: Any) -> bool:
    msg = _dig(body, "message")
    return isinstance(msg, dict) and str(msg.get("status", "0")) != "0"


def motor_limits(body: Any) -> tuple[int, int]:
    """Пределы моторов из json-motor.cgi d=i, по умолчанию как у Sonoff CAM-PT2."""
    msg = _dig(body, "message") if isinstance(_dig(body, "message"), dict) else {}
    try:
        return int(msg.get("xmax") or 3900), int(msg.get("ymax") or 2200)
    except TypeError, ValueError:
        return 3900, 2200


def jog_steps(pan: float, tilt: float, steps_pan: int, steps_tilt: int) -> tuple[int, int]:
    """Сдвиг в шагах моторов. pan и tilt это доля кадра: 1 значит на ширину кадра."""
    return round(pan * steps_pan * JOG), round(tilt * steps_tilt * JOG)


ZONEINFO = "/usr/share/zoneinfo"


def tz_posix(name: str, base: str = ZONEINFO) -> str:
    """Строка часового пояса POSIX (последняя строка файла TZif), ее требует прошивка вместе с именем пояса."""
    if not re.match(r"^[A-Za-z0-9_+\-]+(/[A-Za-z0-9_+\-]+)*$", name or ""):
        return ""
    try:
        with open(f"{base}/{name}", "rb") as f:
            lines = [ln for ln in f.read().split(b"\n") if ln.strip()]
    except OSError:
        return ""
    last = lines[-1].decode(errors="replace").strip() if lines else ""
    return last if last and not last.startswith("TZif") and len(last) < 80 else ""


def time_config(cur: dict[str, Any], tz: str, posix: str, ntp: str) -> dict[str, str]:
    """Настройки времени камеры. Узел Valo первым сервером, публичный пул запасным на случай смены адреса узла."""
    return {
        "action": "update",
        "tz_name": tz,
        "tz_data": posix,
        "ntp_server_0": ntp or str(cur.get("ntp_server_0") or POOL),
        "ntp_server_1": str(cur.get("ntp_server_1") or (POOL if ntp else "")),
        "dhcp_ignore_timezone": "true",
    }
