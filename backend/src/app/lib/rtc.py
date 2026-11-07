"""Адреса и учетные данные внутренней службы видео go2rtc. Наружу служба доступна только через edge."""

import base64
import re

from app.lib.secretbox import derived
from app.lib.settings import env

API_PORT = 1984
RTSP_PORT = 8554
BASE = "/rtc"
USER = "valo"
SUB = "_sub"
NAME = re.compile(r"^[a-z0-9-]{1,64}$")


def host() -> str:
    return env("CAMERAS_HOST", "cameras")


def password() -> str:
    return derived("go2rtc")


def auth_header() -> str:
    return "Basic " + base64.b64encode(f"{USER}:{password()}".encode()).decode()


def api(path: str, local: bool = False) -> str:
    return f"http://{'127.0.0.1' if local else host()}:{API_PORT}{BASE}{path}"


def rtsp(name: str, local: bool = False) -> str:
    return f"rtsp://{USER}:{password()}@{'127.0.0.1' if local else host()}:{RTSP_PORT}/{name}"


def stream(camera_id: str, sub: bool = False) -> str:
    return camera_id + (SUB if sub else "")


def camera_of(name: str) -> str | None:
    base = name.removesuffix(SUB)
    return base if NAME.match(base) else None


def mask(url: str) -> str:
    return re.sub(r"//[^/@]*@", "//***@", url)
