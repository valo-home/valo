import json
import time

import httpx
import pytest

from app.db.base import commit, session
from app.db.models import Device
from app.domain import adapters, ingest, zigbee
from app.lib import tasks
from app.lib.kv import kv

pytestmark = pytest.mark.anyio

PLUG_IEEE = "0xa4c13887ed67a6ba"
LEAK_IEEE = "0xa4c138f5b29d372e"

PLUG_EXPOSES = [
    {
        "type": "switch",
        "features": [
            {"type": "binary", "name": "state", "property": "state", "access": 7, "value_on": "ON", "value_off": "OFF"}
        ],
    },
    {"type": "numeric", "name": "countdown", "property": "countdown", "access": 3, "value_min": 0, "value_max": 43200},
    {
        "type": "enum",
        "name": "power_outage_memory",
        "property": "power_outage_memory",
        "access": 3,
        "values": ["on", "off", "restore"],
    },
    {"type": "numeric", "name": "power", "property": "power", "access": 5, "unit": "W"},
    {"type": "numeric", "name": "current", "property": "current", "access": 5, "unit": "A"},
    {"type": "numeric", "name": "voltage", "property": "voltage", "access": 5, "unit": "V"},
    {"type": "numeric", "name": "energy", "property": "energy", "access": 5, "unit": "kWh"},
    {
        "type": "binary",
        "name": "child_lock",
        "property": "child_lock",
        "access": 3,
        "value_on": "LOCK",
        "value_off": "UNLOCK",
    },
    {"type": "enum", "name": "identify", "property": "identify", "access": 2, "values": ["identify"]},
    {
        "type": "numeric",
        "name": "linkquality",
        "property": "linkquality",
        "access": 1,
        "unit": "lqi",
        "value_min": 0,
        "value_max": 255,
    },
]
LEAK_EXPOSES = [
    {
        "type": "binary",
        "name": "water_leak",
        "property": "water_leak",
        "access": 1,
        "value_on": True,
        "value_off": False,
    },
    {
        "type": "binary",
        "name": "battery_low",
        "property": "battery_low",
        "access": 1,
        "value_on": True,
        "value_off": False,
    },
    {"type": "numeric", "name": "battery", "property": "battery", "access": 1, "unit": "%"},
]


def plug(state: str = "SUCCESSFUL") -> dict:
    item = {
        "ieee_address": PLUG_IEEE,
        "friendly_name": PLUG_IEEE,
        "type": "Router",
        "network_address": 29570,
        "model_id": "TS011F",
        "manufacturer": "Zbeacon",
        "power_source": "Mains (single phase)",
        "interview_state": state,
        "interview_completed": state == "SUCCESSFUL",
        "supported": state == "SUCCESSFUL",
        "software_build_id": "1.0.5\u0000\u0000\u0000",
        "date_code": "\u0000\u0000\u0000\u0000",
    }
    if state == "SUCCESSFUL":
        item["definition"] = {
            "vendor": "Zbeacon",
            "model": "TS011F_plug_1_1",
            "description": "Smart plug (with power monitoring)",
            "exposes": PLUG_EXPOSES,
        }
    return item


LEAK = {
    "ieee_address": LEAK_IEEE,
    "friendly_name": LEAK_IEEE,
    "type": "EndDevice",
    "model_id": "TS0207",
    "power_source": "Battery",
    "interview_state": "SUCCESSFUL",
    "supported": True,
    "definition": {
        "vendor": "HOBEIAN",
        "model": "ZG-222ZA",
        "description": "Water leak sensor",
        "exposes": LEAK_EXPOSES,
    },
}


async def feed(topic: str, payload) -> None:
    raw = json.dumps(payload).encode()
    async with session() as s:
        await ingest.z2m(s, topic, ingest.parse(raw))
        await commit(s)


def test_parse_strips_nul() -> None:
    raw = json.dumps({"software_build_id": "1.0.5\u0000\u0000", "nested": [{"x": "\u0000a"}]}).encode()
    assert ingest.parse(raw) == {"software_build_id": "1.0.5", "nested": [{"x": "a"}]}
    assert ingest.parse(b"plain\x00") == "plain"
    assert ingest.parse(b"") == ""


def test_plug_caps_mapping() -> None:
    caps, conv = adapters.z2m_caps(PLUG_EXPOSES)
    by = {c["id"]: c for c in caps}
    assert by["on"]["access"] == "rw" and by["w"]["unit"] == "W" and by["kwh"]["unit"] == "kWh"
    assert by["lock"]["type"] == "bool" and by["identify"]["access"] == "w"
    assert adapters.kind_of(caps) == "plug"
    assert adapters.z2m_in(conv, {"state": "ON", "power": 12.5, "child_lock": "LOCK"}) == {
        "on": True,
        "w": 12.5,
        "lock": True,
    }
    assert adapters.z2m_out(conv, {"on": False, "lock": False}) == {"state": "OFF", "child_lock": "UNLOCK"}


async def test_interview_then_definition(client: httpx.AsyncClient, owner: dict) -> None:
    await feed("bridge/devices", [{"type": "Coordinator", "ieee_address": "0x70c59cfffe47fcd0"}, plug("IN_PROGRESS")])
    r = (await client.get(f"/api/v1/devices/{PLUG_IEEE}", headers=owner)).json()
    assert r["name"] == PLUG_IEEE and r["caps"] == [] and r["attrs"]["interviewed"] is False
    assert r["attrs"]["sw"] == "1.0.5"
    await feed("bridge/devices", [plug(), LEAK])
    r = (await client.get(f"/api/v1/devices/{PLUG_IEEE}", headers=owner)).json()
    assert r["name"] == "Smart plug (with power monitoring)" and r["kind"] == "plug"
    assert r["attrs"]["interviewed"] is True and {"on", "w", "kwh"} <= {c["id"] for c in r["caps"]}
    await client.patch(f"/api/v1/devices/{PLUG_IEEE}", json={"name": "Розетка в кухне"}, headers=owner)
    await feed("bridge/devices", [plug(), LEAK])
    r = (await client.get(f"/api/v1/devices/{PLUG_IEEE}", headers=owner)).json()
    assert r["name"] == "Розетка в кухне"


async def test_bad_item_does_not_drop_batch(client: httpx.AsyncClient, owner: dict, monkeypatch) -> None:
    real = ingest._z2m_item

    async def flaky(s, ieee, it):
        if ieee == PLUG_IEEE:
            raise RuntimeError("broken definition")
        await real(s, ieee, it)

    monkeypatch.setattr(ingest, "_z2m_item", flaky)
    await feed("bridge/devices", [plug(), LEAK])
    assert (await client.get(f"/api/v1/devices/{LEAK_IEEE}", headers=owner)).status_code == 200
    assert (await client.get(f"/api/v1/devices/{PLUG_IEEE}", headers=owner)).status_code == 404


async def test_state_availability_and_leak_alarm(client: httpx.AsyncClient, owner: dict) -> None:
    await feed("bridge/devices", [plug(), LEAK])
    await feed(PLUG_IEEE, {"state": "OFF", "power": 0, "voltage": 249, "linkquality": 220, "update": {"state": "idle"}})
    d = (await client.get(f"/api/v1/devices/{PLUG_IEEE}", headers=owner)).json()
    assert d["state"]["on"] is False and d["state"]["v"] == 249 and d["attrs"]["lqi"] == 220
    await feed(f"{PLUG_IEEE}/availability", {"state": "offline"})
    assert (await client.get(f"/api/v1/devices/{PLUG_IEEE}", headers=owner)).json()["available"] is False
    await feed(f"{PLUG_IEEE}/availability", {"state": "online"})
    assert (await client.get(f"/api/v1/devices/{PLUG_IEEE}", headers=owner)).json()["available"] is True
    await feed(LEAK_IEEE, {"water_leak": True, "battery": 100, "battery_low": False})
    d = (await client.get(f"/api/v1/devices/{LEAK_IEEE}", headers=owner)).json()
    assert d["state"]["leak"] is True
    notes = (await client.get("/api/v1/notifications", headers=owner)).json()
    assert any(n["level"] == "crit" for n in notes)


async def test_bridge_events_and_removal(client: httpx.AsyncClient, owner: dict) -> None:
    await feed("bridge/state", {"state": "online"})
    assert await kv().get("z2m:state") == "online"
    await feed("bridge/devices", [plug(), LEAK])
    await feed(
        "bridge/event", {"type": "device_joined", "data": {"ieee_address": PLUG_IEEE, "friendly_name": PLUG_IEEE}}
    )
    await feed(
        "bridge/event",
        {
            "type": "device_interview",
            "data": {"ieee_address": PLUG_IEEE, "status": "successful", "definition": {"model": "TS011F_plug_1_1"}},
        },
    )
    evs = (await client.get("/api/v1/events", headers=owner)).json()
    types = {e["type"] for e in evs}
    assert {"zigbee.device_joined", "zigbee.interview_successful", "zigbee.online", "device.added"} <= types
    await feed("bridge/devices", [LEAK])
    assert (await client.get(f"/api/v1/devices/{PLUG_IEEE}", headers=owner)).status_code == 404
    async with session() as s:
        assert await s.get(Device, LEAK_IEEE) is not None
    await feed("bridge/state", {"state": "offline"})
    assert await kv().zscore("timers", "z2m:offline")


async def test_z2m_alert_waits_for_configured_minutes_then_reports_recovery(
    client: httpx.AsyncClient, owner: dict, monkeypatch
) -> None:
    pushed: list[dict] = []
    real_kick = tasks.kick

    async def kick(name: str, /, **kw) -> None:
        if name == "ext.push":
            pushed.append(kw)
            return
        await real_kick(name, **kw)

    monkeypatch.setattr(tasks, "kick", kick)

    async def z2m_notes() -> list[dict]:
        notes = (await client.get("/api/v1/notifications", headers=owner)).json()
        return [n for n in notes if n["type"] == "z2m_offline"]

    await feed("bridge/state", {"state": "online"})
    await feed("bridge/state", {"state": "offline"})
    due = await kv().zscore("timers", "z2m:offline")
    assert due and 170 < due - time.time() <= 180
    assert not await z2m_notes() and not pushed
    await feed("bridge/state", {"state": "online"})
    assert await kv().zscore("timers", "z2m:offline") is None
    assert not pushed
    evs = {e["type"] for e in (await client.get("/api/v1/events", headers=owner)).json()}
    assert {"zigbee.offline", "zigbee.online"} <= evs

    await feed("bridge/state", {"state": "offline"})
    await kv().set("z2m:offline_at", str(time.time() - 300))
    await kv().zadd("timers", {"z2m:offline": time.time() - 1})
    await tasks.pump()
    assert len(await z2m_notes()) == 1
    assert [p["type"] for p in pushed] == ["z2m_offline"]
    await feed("bridge/state", {"state": "online"})
    assert not await z2m_notes()
    assert pushed[-1] == {"type": "z2m_online", "level": "info", "params": {"min": 5}, "force": True}

    r = await client.patch("/api/v1/home", headers=owner, json={"settings": {"z2mAlertMinutes": 0}})
    assert r.status_code == 200
    pushed.clear()
    await feed("bridge/state", {"state": "offline"})
    assert await kv().zscore("timers", "z2m:offline") is None
    assert len(await z2m_notes()) == 1 and [p["type"] for p in pushed] == ["z2m_offline"]
    await feed("bridge/state", {"state": "online"})
    assert pushed[-1]["type"] == "z2m_online"


def test_z2m_alert_minutes_setting_is_clamped() -> None:
    assert zigbee.alert_minutes({}) == 3
    assert zigbee.alert_minutes({"z2mAlertMinutes": 10}) == 10
    assert zigbee.alert_minutes({"z2mAlertMinutes": -5}) == 0
    assert zigbee.alert_minutes({"z2mAlertMinutes": 999}) == 60
    assert zigbee.alert_minutes({"z2mAlertMinutes": "x"}) == 3
    assert zigbee.alert_minutes({"z2mAlertMinutes": True}) == 3


SMOKE_CO_IEEE = "0xa4c1380000513c0d"
SMOKE_CO = {
    "ieee_address": SMOKE_CO_IEEE,
    "friendly_name": SMOKE_CO_IEEE,
    "type": "EndDevice",
    "model_id": "TS0601",
    "manufacturer": "_TZE284_aoah6bv8",
    "power_source": "Battery",
    "interview_state": "SUCCESSFUL",
    "supported": True,
    "definition": {
        "vendor": "Moes",
        "model": "JKD-513COM-Z",
        "description": "Dual smoke & CO alarm",
        "exposes": [
            {"type": "binary", "name": "smoke", "property": "smoke", "access": 1, "value_on": True, "value_off": False},
            {
                "type": "enum",
                "name": "smoke_state",
                "property": "smoke_state",
                "access": 1,
                "values": ["alarm", "none", "detecting", "unknown"],
            },
            {
                "type": "enum",
                "name": "alarm_volume",
                "property": "alarm_volume",
                "access": 3,
                "values": ["mute", "low", "medium", "high"],
            },
            {
                "type": "numeric",
                "name": "battery",
                "property": "battery",
                "access": 1,
                "unit": "%",
                "value_min": 0,
                "value_max": 100,
            },
            {
                "type": "binary",
                "name": "silence",
                "property": "silence",
                "access": 3,
                "value_on": True,
                "value_off": False,
            },
            {
                "type": "binary",
                "name": "alarm_switch",
                "property": "alarm_switch",
                "access": 3,
                "value_on": True,
                "value_off": False,
            },
            {
                "type": "binary",
                "name": "carbon_monoxide",
                "property": "carbon_monoxide",
                "access": 1,
                "value_on": True,
                "value_off": False,
            },
        ],
    },
}


async def test_moes_smoke_co_alarm(client: httpx.AsyncClient, owner: dict, published: list) -> None:
    await feed("bridge/devices", [SMOKE_CO])
    d = (await client.get(f"/api/v1/devices/{SMOKE_CO_IEEE}", headers=owner)).json()
    assert d["kind"] == "smoke" and d["name"] == "Dual smoke & CO alarm"
    by = {c["id"]: c for c in d["caps"]}
    assert set(by) == {"smoke", "smoke_state", "alarm_volume", "bat", "silence", "alarm_switch", "co"}
    assert by["alarm_volume"]["access"] == "rw" and by["co"]["access"] == "r"
    await feed(SMOKE_CO_IEEE, {"smoke": False, "smoke_state": "none", "carbon_monoxide": False, "battery": 90})
    await feed(SMOKE_CO_IEEE, {"carbon_monoxide": True})
    notes = (await client.get("/api/v1/notifications", headers=owner)).json()
    assert any(n["type"] == "co" and n["level"] == "crit" for n in notes)
    await feed(SMOKE_CO_IEEE, {"carbon_monoxide": False})
    notes = (await client.get("/api/v1/notifications", headers=owner)).json()
    assert not any(n["type"] == "co" for n in notes)
    r = await client.post(
        f"/api/v1/devices/{SMOKE_CO_IEEE}/command", json={"values": {"alarm_volume": "low"}}, headers=owner
    )
    assert r.status_code == 202
    assert (f"zigbee2mqtt/{SMOKE_CO_IEEE}/set", {"alarm_volume": "low"}) in published
    r = await client.post(f"/api/v1/devices/{SMOKE_CO_IEEE}/command", json={"values": {"silence": True}}, headers=owner)
    assert (f"zigbee2mqtt/{SMOKE_CO_IEEE}/set", {"silence": True}) in published


SMOKE_IEEE = "0xa4c138e227c5301e"
SMOKE = {
    "ieee_address": SMOKE_IEEE,
    "friendly_name": SMOKE_IEEE,
    "type": "EndDevice",
    "model_id": "TS0601",
    "manufacturer": "_TZE2841000000_rccxox8p",
    "power_source": "Battery",
    "interview_state": "SUCCESSFUL",
    "supported": True,
    "definition": {
        "vendor": "Tuya",
        "model": "PA-44Z",
        "description": "Photoelectric smoke detector",
        "supports_ota": False,
        "exposes": [
            {"type": "binary", "property": "smoke", "access": 1, "value_on": True, "value_off": False},
            {"type": "numeric", "property": "battery", "access": 1, "unit": "%"},
            {"type": "binary", "property": "silence", "access": 3, "value_on": True, "value_off": False},
            {"type": "binary", "property": "test", "access": 1, "value_on": True, "value_off": False},
            {"type": "numeric", "property": "smoke_concentration", "access": 1, "unit": "ppm"},
            {"type": "binary", "property": "device_fault", "access": 1, "value_on": True, "value_off": False},
            {"type": "numeric", "property": "linkquality", "access": 1, "unit": "lqi"},
        ],
    },
}


async def test_ota_unsupported_is_refused_locally(client: httpx.AsyncClient, owner: dict, published: list) -> None:
    await feed("bridge/devices", [SMOKE, plug()])
    d = (await client.get(f"/api/v1/devices/{SMOKE_IEEE}", headers=owner)).json()
    assert d["kind"] == "smoke" and d["attrs"]["otaSupported"] is False
    assert {"smoke", "bat", "silence", "test", "smoke_concentration", "device_fault"} <= {c["id"] for c in d["caps"]}
    published.clear()
    r = await client.post(f"/api/v1/zigbee/devices/{SMOKE_IEEE}/ota-check", json={}, headers=owner)
    assert r.status_code == 422 and r.json()["code"] == "ota_unsupported"
    r = await client.post(f"/api/v1/zigbee/devices/{SMOKE_IEEE}/ota-update", json={}, headers=owner)
    assert r.status_code == 422
    assert not [t for t, _ in published if "ota_update" in t]
    p = (await client.get(f"/api/v1/devices/{PLUG_IEEE}", headers=owner)).json()
    assert p["attrs"]["otaSupported"] is False


async def test_notification_page_shows_details_related_log_and_history(client: httpx.AsyncClient, owner: dict) -> None:
    await feed("bridge/state", {"state": "online"})
    await client.patch("/api/v1/home", headers=owner, json={"settings": {"z2mAlertMinutes": 0}})
    await feed("bridge/state", {"state": "offline"})
    active = (await client.get("/api/v1/notifications", headers=owner)).json()
    n = next(x for x in active if x["type"] == "z2m_offline")
    assert n["dismissedAt"] is None
    d = (await client.get(f"/api/v1/notifications/{n['id']}", headers=owner)).json()
    assert d["route"] == "zigbee" and d["level"] == "crit"
    assert [e["type"] for e in d["events"]][:2] == ["zigbee.offline", "zigbee.online"]
    assert all(e["type"].startswith("zigbee.") for e in d["events"])
    assert d["log"] == []
    await feed("bridge/state", {"state": "online"})
    assert not any(x["id"] == n["id"] for x in (await client.get("/api/v1/notifications", headers=owner)).json())
    hist = (await client.get("/api/v1/notifications?history=true", headers=owner)).json()
    closed = next(x for x in hist if x["id"] == n["id"])
    assert closed["dismissedAt"]
    d = (await client.get(f"/api/v1/notifications/{n['id']}", headers=owner)).json()
    assert d["dismissedAt"] and d["events"][0]["type"] == "zigbee.online"
    assert (await client.get("/api/v1/notifications/999999", headers=owner)).status_code == 404
