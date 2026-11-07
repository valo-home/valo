from datetime import date, datetime

import httpx
import pytest

from app.db.base import commit, session
from app.domain import adapters, devices, ingest
from app.lib.kv import kv
from app.lib.timeutil import cron_match, sun, zone

pytestmark = pytest.mark.anyio

LAMP = {
    "ieee_address": "0x00158d0001a2b3c4",
    "type": "Router",
    "network_address": 1234,
    "friendly_name": "0x00158d0001a2b3c4",
    "supported": True,
    "definition": {
        "vendor": "IKEA",
        "model": "LED2003G10",
        "description": "TRADFRI bulb",
        "exposes": [
            {
                "type": "light",
                "features": [
                    {"type": "binary", "property": "state", "access": 7, "value_on": "ON", "value_off": "OFF"},
                    {"type": "numeric", "property": "brightness", "access": 7, "value_min": 0, "value_max": 254},
                    {"type": "numeric", "property": "color_temp", "access": 7, "value_min": 250, "value_max": 454},
                ],
            },
            {"type": "numeric", "property": "linkquality", "access": 1, "unit": "lqi"},
        ],
    },
}
MOTION = {
    "ieee_address": "0x00158d0002b3c4d5",
    "type": "EndDevice",
    "friendly_name": "0x00158d0002b3c4d5",
    "definition": {
        "vendor": "Aqara",
        "model": "RTCGQ11LM",
        "description": "Motion sensor",
        "exposes": [
            {"type": "binary", "property": "occupancy", "access": 1, "value_on": True, "value_off": False},
            {"type": "numeric", "property": "illuminance_lux", "access": 1, "unit": "lx"},
            {"type": "numeric", "property": "battery", "access": 1, "unit": "%"},
        ],
    },
}


async def z2m(sub: str, payload) -> None:
    async with session() as s:
        await ingest.z2m(s, sub, payload)
        await commit(s)


def test_units() -> None:
    tz = zone("Europe/Helsinki")
    assert cron_match("*/15 7-9 * * 1-5", datetime(2026, 11, 2, 7, 30, tzinfo=tz))
    assert not cron_match("0 7 * * 6,0", datetime(2026, 11, 2, 7, 0, tzinfo=tz))
    mode, rise, sset = sun(date(2026, 10, 31), 60.205, 24.655, tz)
    assert mode == "normal" and rise and sset and 7 <= rise.hour <= 9 and 15 <= sset.hour <= 17
    assert sun(date(2026, 12, 21), 78.22, 15.65, zone("Arctic/Longyearbyen"))[0] == "night"
    caps, conv = adapters.z2m_caps(LAMP["definition"]["exposes"])
    assert {c["id"] for c in caps} >= {"on", "bri", "ct", "lqi"}
    assert adapters.z2m_in(conv, {"state": "ON", "brightness": 127, "color_temp": 370}) == {
        "on": True,
        "bri": 50,
        "ct": 2703,
    }
    assert adapters.z2m_out(conv, {"bri": 100, "on": False}) == {"brightness": 254, "state": "OFF"}
    assert adapters.render("{{ value_json.temp | round(1) }}", {"temp": 21.456}) == 21.5
    assert adapters.render("{{ value_json['a'].b }}", {"a": {"b": 3}}) == 3


async def test_setup_login(client: httpx.AsyncClient, owner: dict) -> None:
    r = await client.get("/api/v1/auth/me", headers=owner)
    assert r.json()["username"] == "mikko"
    r = await client.post(
        "/api/v1/auth/login", json={"username": "mikko", "password": "wrong"}, headers={"Accept-Language": "ru"}
    )
    assert r.status_code == 401 and r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["title"] == "Неверное имя пользователя или пароль"
    assert (await client.get("/api/v1/devices")).status_code == 401
    assert (
        await client.post(
            "/api/v1/setup", json={"owner": {"username": "x", "name": "x", "password": "secret123"}, "home": {}}
        )
    ).status_code == 409


async def test_zigbee_command_cycle(client: httpx.AsyncClient, owner: dict, published: list) -> None:
    await z2m("bridge/devices", [{"type": "Coordinator", "ieee_address": "0x0"}, LAMP, MOTION])
    await z2m("0x00158d0001a2b3c4", {"state": "OFF", "brightness": 254, "linkquality": 120})
    r = await client.get("/api/v1/devices/0x00158d0001a2b3c4", headers=owner)
    d = r.json()
    assert d["kind"] == "light" and d["state"]["on"] is False and d["attrs"]["lqi"] == 120
    r = await client.post(
        "/api/v1/devices/0x00158d0001a2b3c4/command", json={"values": {"on": True, "bri": 40}}, headers=owner
    )
    assert r.status_code == 202, r.text
    cmd = r.json()
    assert ("zigbee2mqtt/0x00158d0001a2b3c4/set", {"state": "ON", "brightness": 102}) in published
    assert await kv().scard("cmd:pending:0x00158d0001a2b3c4") == 1
    await z2m("0x00158d0001a2b3c4", {"state": "ON", "brightness": 102})
    r = await client.get("/api/v1/devices/0x00158d0001a2b3c4/commands", headers=owner)
    assert r.json()[0]["id"] == cmd["id"] and r.json()[0]["status"] == "ok"
    r = await client.post("/api/v1/devices/0x00158d0001a2b3c4/command", json={"values": {"bri": 140}}, headers=owner)
    assert r.status_code == 422 and r.json()["code"] == "value_invalid"
    r = await client.post("/api/v1/devices/0x00158d0002b3c4d5/command", json={"values": {"occ": True}}, headers=owner)
    assert r.json()["code"] == "cap_not_writable"


async def test_timeout_and_scene_partial(client: httpx.AsyncClient, owner: dict) -> None:
    await z2m("bridge/devices", [LAMP])
    await z2m("0x00158d0001a2b3c4", {"state": "OFF"})
    r = await client.post(
        "/api/v1/scenes", json={"name": "Вечер", "actions": {"0x00158d0001a2b3c4": {"on": True}}}, headers=owner
    )
    assert r.status_code == 201
    r = await client.post(f"/api/v1/scenes/{r.json()['id']}/apply", headers=owner)
    assert r.json()["sent"] == ["0x00158d0001a2b3c4"]
    async with session() as s:
        cmds = await devices.commands(s, "0x00158d0001a2b3c4")
        await devices.timeout(s, str(cmds[0].id))
        await commit(s)
    r = await client.get("/api/v1/events?kind=scene", headers=owner)
    assert any(e["type"] == "scene.partial" and e["params"]["failed"] == ["TRADFRI bulb"] for e in r.json())
    r = await client.get("/api/v1/notifications", headers=owner)
    assert any(n["type"] == "command_timeout" for n in r.json())


async def test_flow_dispatch_and_dry_run(client: httpx.AsyncClient, owner: dict, published: list) -> None:
    await z2m("bridge/devices", [LAMP, MOTION])
    await z2m("0x00158d0002b3c4d5", {"occupancy": False, "illuminance_lux": 12})
    await z2m("0x00158d0001a2b3c4", {"state": "OFF"})
    graph = {
        "nodes": [
            {"id": "t", "block": "state", "params": {"device": "0x00158d0002b3c4d5", "cap": "occ", "to": True}},
            {
                "id": "c",
                "block": "compare",
                "params": {"device": "0x00158d0002b3c4d5", "cap": "lux", "op": "lt", "value": 40},
            },
            {"id": "a", "block": "command", "params": {"device": "0x00158d0001a2b3c4", "values": {"on": True}}},
        ],
        "edges": [{"from": "t", "out": 0, "to": "c", "in": 0}, {"from": "c", "out": 0, "to": "a", "in": 0}],
    }
    r = await client.post("/api/v1/flows", json={"name": "Кухня по движению", "graph": graph}, headers=owner)
    assert r.status_code == 201, r.text
    fid = r.json()["id"]
    bad = {**graph, "edges": [{"from": "t", "out": 0, "to": "x", "in": 0}]}
    assert (await client.patch(f"/api/v1/flows/{fid}", json={"graph": bad}, headers=owner)).status_code == 422
    r = await client.post(f"/api/v1/flows/{fid}/test", json={}, headers=owner)
    res = r.json()
    assert res["status"] == "ok" and [t["m"] for t in res["trace"]] == ["trigger", "compare", "dry_command"]
    published.clear()
    async with session() as s:
        from app.domain import flows

        await flows.reindex(s)
    assert await kv().sismember("flows:trig", "state:0x00158d0002b3c4d5")
    await z2m("0x00158d0002b3c4d5", {"occupancy": True})
    assert ("zigbee2mqtt/0x00158d0001a2b3c4/set", {"state": "ON"}) in published
    r = await client.get(f"/api/v1/flows/{fid}", headers=owner)
    assert r.json()["lastResult"] == "ok" and r.json()["runs"] == 1


async def test_ha_discovery_and_hub(client: httpx.AsyncClient, owner: dict, published: list) -> None:
    cfg = {
        "dev": {"ids": "esphome-boiler", "name": "Бойлер", "mf": "Espressif"},
        "o": {"name": "esphome"},
        "cmps": {
            "relay": {
                "p": "switch",
                "uniq_id": "boiler_relay",
                "stat_t": "esphome-boiler/switch/relay/state",
                "cmd_t": "esphome-boiler/switch/relay/command",
            },
            "power": {
                "p": "sensor",
                "dev_cla": "power",
                "unit_of_meas": "W",
                "stat_t": "esphome-boiler/sensor/power/state",
            },
        },
    }
    async with session() as s:
        await ingest.ha_config(s, "homeassistant/device/esphome-boiler/config", cfg)
        await commit(s)
    idx = await _index()
    async with session() as s:
        await ingest.mapped(
            s, "esphome-boiler/sensor/power/state", ingest.parse(b"2950.5"), idx["esphome-boiler/sensor/power/state"]
        )
        await commit(s)
    d = (await client.get("/api/v1/devices/ha-esphome-boiler", headers=owner)).json()
    assert d["state"]["w"] == 2950.5 and {c["id"] for c in d["caps"]} == {"on", "w"}
    await client.post("/api/v1/devices/ha-esphome-boiler/command", json={"values": {"on": True}}, headers=owner)
    assert ("esphome-boiler/switch/relay/command", "ON") in published
    meta = {
        "name": "Каменка",
        "kind": "sauna",
        "caps": [{"id": "on", "type": "bool", "access": "rw"}, {"id": "t", "type": "num", "access": "r"}],
    }
    async with session() as s:
        await ingest.hub(s, "hub/v1/dev/sauna-ctrl/meta", meta)
        await ingest.hub(s, "hub/v1/dev/sauna-ctrl/state", {"on": False, "t": 54.2})
        await commit(s)
    r = await client.post("/api/v1/devices/sauna-ctrl/command", json={"values": {"on": True}}, headers=owner)
    cid = r.json()["id"]
    assert ("hub/v1/dev/sauna-ctrl/set", {"cmd": cid, "values": {"on": True}}) in published
    async with session() as s:
        d = await devices.get(s, "sauna-ctrl")
        await ingest.hub(s, "hub/v1/dev/sauna-ctrl/ack", {"cmd": cid, "ok": True, "values": {"on": True}})
        await commit(s)
    r = await client.get("/api/v1/devices/sauna-ctrl/commands", headers=owner)
    assert r.json()[0]["status"] == "ok"


async def _index() -> dict:
    async with session() as s:
        return await devices.index(s)


async def test_roles(client: httpx.AsyncClient, owner: dict) -> None:
    r = await client.post(
        "/api/v1/users",
        json={"username": "elias", "name": "Elias", "password": "secret123", "role": "member", "rooms": ["kids"]},
        headers=owner,
    )
    assert r.status_code == 201
    r = await client.post("/api/v1/auth/login", json={"username": "elias", "password": "secret123"})
    member = {"Authorization": f"Bearer {r.json()['token']}"}
    assert (await client.post("/api/v1/flows", json={"name": "x"}, headers=member)).status_code == 403
    assert (await client.get("/api/v1/users", headers=member)).status_code == 403
    r = await client.post("/api/v1/tokens", json={"name": "Grafana", "scope": "read"}, headers=owner)
    tok = {"Authorization": f"Bearer {r.json()['token']}"}
    assert (await client.get("/api/v1/devices", headers=tok)).status_code == 200
    assert (await client.post("/api/v1/scenes", json={"name": "x"}, headers=tok)).status_code == 403


async def test_room_plan_keeps_device_positions_and_rejects_bad_geometry(
    client: httpx.AsyncClient, owner: dict
) -> None:
    room = (await client.post("/api/v1/rooms", json={"name": "Гостиная", "floor": 1}, headers=owner)).json()
    url = f"/api/v1/rooms/{room['id']}"
    geom = {"x": 20, "y": 20, "w": 200, "h": 140, "devs": {"plug-1": [0.25, 0.5], "lamp": [1, 0]}}
    r = await client.patch(url, json={"geom": geom}, headers=owner)
    assert r.status_code == 200, r.text
    assert r.json()["geom"]["devs"] == {"plug-1": [0.25, 0.5], "lamp": [1.0, 0.0]}
    bad = [
        {**geom, "devs": {"plug-1": [1.5, 0]}},
        {**geom, "devs": {"plug-1": [0.1]}},
        {**geom, "color": "red"},
        {"x": 0, "y": 0, "w": 0, "h": 10},
        {"x": "1", "y": 0, "w": 10, "h": 10},
    ]
    for g in bad:
        r = await client.patch(url, json={"geom": g}, headers=owner)
        assert r.status_code == 422, (g, r.text)
    r = await client.patch(url, json={"geom": {}}, headers=owner)
    assert r.json()["geom"] == {}
