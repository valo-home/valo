"""Выбор координатора Zigbee в интерфейсе. Служба zigbee2mqtt ждет выбора и берет его из общего тома."""

import os
import pathlib
import re
from typing import Any

from app.domain.common import S
from app.lib import log
from app.lib.errors import ApplicationError
from app.lib.settings import env

TYPES = ("ember", "zstack", "deconz", "zigate", "zboss")
_log = log.get("coordinator")


class AdapterIn(S):
    path: str
    type: str


def host_dev() -> pathlib.Path:
    return pathlib.Path(env("HOST_DEV", "/host-dev"))


def conf_file() -> pathlib.Path:
    return pathlib.Path(env("ZIGBEE_CONF", "/valo-zigbee/adapter.env"))


def guess(name: str) -> str:
    """Тип прошивки координатора по имени устройства USB. Пусто, если по имени не понять."""
    n = name.lower()
    if any(k in n for k in ("dongle_plus_v2", "dongle-e", "dongle_e", "zbt-1", "skyconnect", "efr32", "silicon_labs")):
        return "ember"
    if any(k in n for k in ("dongle_plus", "dongle-p", "cc2652", "cc1352", "cc2531", "slaesh", "zzh", "texas")):
        return "zstack"
    if any(k in n for k in ("conbee", "raspbee", "dresden")):
        return "deconz"
    if "zigate" in n:
        return "zigate"
    return ""


def pretty(name: str) -> str:
    n = re.sub(r"^(usb|pci)-", "", name)
    n = re.sub(r"-if\d+(-port\d+)?$", "", n)
    n = re.sub(r"_[0-9a-f]{12,}$", "", n, flags=re.I)
    return n.replace("_", " ").strip()


def adapters() -> list[dict[str, Any]]:
    base = host_dev() / "serial" / "by-id"
    if not base.is_dir():
        return []
    out = []
    for f in sorted(base.iterdir()):
        out.append({"path": f"/dev/serial/by-id/{f.name}", "name": pretty(f.name), "type": guess(f.name)})
    return out


def parse(text: str) -> dict[str, str]:
    out = {}
    for line in text.splitlines():
        k, sep, v = line.partition("=")
        if sep:
            out[k.strip()] = v.strip()
    return out


def current() -> dict[str, Any] | None:
    port = env("ZIGBEE_ADAPTER")
    if port:
        return {"path": port, "type": env("ZIGBEE_ADAPTER_TYPE"), "source": "env"}
    f = conf_file()
    if f.is_file():
        c = parse(f.read_text())
        if c.get("port"):
            return {"path": c["port"], "type": c.get("adapter", ""), "source": "ui"}
    return None


def status() -> dict[str, Any]:
    return {"adapters": adapters(), "current": current(), "types": list(TYPES)}


def choose(data: AdapterIn) -> dict[str, Any]:
    cur = current()
    if cur and cur["source"] == "env":
        raise ApplicationError("zigbee_adapter_fixed", 409, path=cur["path"])
    known = {a["path"] for a in adapters()}
    if data.path not in known:
        raise ApplicationError("zigbee_adapter_unknown", 422, path=data.path)
    if data.type not in TYPES:
        raise ApplicationError("validation", 422, detail="type")
    f = conf_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_name(f".{f.name}.tmp")
    tmp.write_text(f"port={data.path}\nadapter={data.type}\n")
    os.replace(tmp, f)
    _log.info("zigbee_adapter_chosen", path=data.path, type=data.type)
    return status()
