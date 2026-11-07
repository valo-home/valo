import httpx
import pytest

from app.db.base import commit, session
from app.domain import flows, ingest
from app.lib import tasks
from app.lib.kv import kv

pytestmark = pytest.mark.anyio

PLUG = "0xa4c13887ed67a6ba"
PLUG_ITEM = {
    "ieee_address": PLUG,
    "friendly_name": PLUG,
    "type": "Router",
    "interview_state": "SUCCESSFUL",
    "definition": {
        "vendor": "Zbeacon",
        "model": "TS011F_plug_1_1",
        "description": "Smart plug",
        "exposes": [
            {
                "type": "switch",
                "features": [
                    {"type": "binary", "property": "state", "access": 7, "value_on": "ON", "value_off": "OFF"}
                ],
            },
            {"type": "numeric", "property": "power", "access": 5, "unit": "W"},
        ],
    },
}
CYCLE = {
    "nodes": [
        {"id": "m", "block": "manual", "params": {}},
        {"id": "a", "block": "command", "params": {"device": PLUG, "values": {"on": True}}},
        {"id": "d", "block": "delay", "params": {"seconds": 300}},
        {"id": "o", "block": "command", "params": {"device": PLUG, "values": {"on": False}}},
    ],
    "edges": [
        {"from": "m", "out": 0, "to": "a", "in": 0},
        {"from": "a", "out": 0, "to": "d", "in": 0},
        {"from": "d", "out": 0, "to": "o", "in": 0},
    ],
}
SET = f"zigbee2mqtt/{PLUG}/set"


async def plug() -> None:
    async with session() as s:
        await ingest.z2m(s, "bridge/devices", [PLUG_ITEM])
        await ingest.z2m(s, PLUG, {"state": "OFF", "power": 0})
        await commit(s)


async def fire_timers() -> int:
    for key in await kv().zrange("timers", 0, -1):
        await kv().zadd("timers", {key: 0})
    return await tasks.pump()


async def test_delay_survives_as_timer_and_resumes(client: httpx.AsyncClient, owner: dict, published: list) -> None:
    await plug()
    r = await client.post("/api/v1/flows", json={"name": "Цикл розетки", "graph": CYCLE}, headers=owner)
    assert r.status_code == 201, r.text
    fid = r.json()["id"]
    r = await client.post(f"/api/v1/flows/{fid}/run", json={}, headers=owner)
    assert r.status_code == 200 and r.json()["status"] == "wait", r.text
    assert (SET, {"state": "ON"}) in published and (SET, {"state": "OFF"}) not in published
    assert await kv().zcard("timers") >= 1
    second = await client.post(f"/api/v1/flows/{fid}/run", json={}, headers=owner)
    assert second.json()["status"] == "skip"
    assert await fire_timers() >= 1
    assert (SET, {"state": "OFF"}) in published
    runs = (await client.get(f"/api/v1/flows/{fid}/runs", headers=owner)).json()
    assert runs[0]["status"] == "ok"
    assert [t["m"] for t in runs[0]["trace"]][-1] == "command"


async def test_dry_run_sends_nothing(client: httpx.AsyncClient, owner: dict, published: list) -> None:
    await plug()
    fid = (await client.post("/api/v1/flows", json={"name": "x", "graph": CYCLE}, headers=owner)).json()["id"]
    published.clear()
    res = (await client.post(f"/api/v1/flows/{fid}/test", json={}, headers=owner)).json()
    assert res["status"] == "ok"
    assert [t["m"] for t in res["trace"]] == ["trigger", "dry_command", "dry_delay", "dry_command"]
    assert not [p for p in published if p[0] == SET]


async def test_versions_and_restore(client: httpx.AsyncClient, owner: dict) -> None:
    await plug()
    fid = (await client.post("/api/v1/flows", json={"name": "v", "graph": CYCLE}, headers=owner)).json()["id"]
    g2 = {**CYCLE, "nodes": [*CYCLE["nodes"][:2], {**CYCLE["nodes"][2], "params": {"seconds": 60}}, CYCLE["nodes"][3]]}
    r = await client.patch(f"/api/v1/flows/{fid}", json={"graph": g2}, headers=owner)
    assert r.status_code == 200 and r.json()["version"] == 2
    vers = (await client.get(f"/api/v1/flows/{fid}/versions", headers=owner)).json()
    assert sorted(v["version"] for v in vers) == [1, 2]
    r = await client.post(f"/api/v1/flows/{fid}/versions/1/restore", json={}, headers=owner)
    assert r.status_code == 200
    delay = next(n for n in r.json()["graph"]["nodes"] if n["id"] == "d")
    assert delay["params"]["seconds"] == 300


async def test_templates_use_known_blocks(client: httpx.AsyncClient, owner: dict) -> None:
    async with session() as s:
        reg = await flows.registry(s)
    keys = {t["key"] for t in flows.TEMPLATES}
    assert "plug_cycle" in keys
    for t in flows.TEMPLATES:
        assert not flows.dead_blocks(t["graph"], reg), t["key"]
    r = await client.get("/api/v1/flows/templates", headers=owner)
    assert {t["key"] for t in r.json()} == keys


async def test_device_commands_and_events_page_with_cursor(client: httpx.AsyncClient, owner: dict) -> None:
    from datetime import UTC, datetime, timedelta

    from app.db.base import commit, session
    from app.db.models import Command, Device

    async with session() as s:
        s.add(
            Device(
                id="pg-dev",
                name="Pager",
                source="mqtt",
                kind="plug",
                model="",
                vendor="",
                address="pg-dev",
                caps=[],
                state={},
                attrs={},
            )
        )
        await s.flush()
        base = datetime(2026, 11, 1, tzinfo=UTC)
        for i in range(7):
            s.add(
                Command(
                    id=f"00000000-0000-7000-8000-00000000000{i}",
                    device_id="pg-dev",
                    values={"on": True},
                    status="ok",
                    actor="t",
                    created_at=base + timedelta(minutes=[0, 1, 2, 3, 3, 3, 6][i]),
                )
            )
        await commit(s)
    r = await client.get("/api/v1/devices/pg-dev/commands?limit=3", headers=owner)
    first = r.json()
    assert [c["id"][-1] for c in first] == ["6", "5", "4"]
    r = await client.get(
        "/api/v1/devices/pg-dev/commands",
        params={"limit": 3, "before": f"{first[-1]['createdAt']}|{first[-1]['id']}"},
        headers=owner,
    )
    assert [c["id"][-1] for c in r.json()] == ["3", "2", "1"]
    r = await client.get("/api/v1/devices/pg-dev/events?limit=500", headers=owner)
    assert r.status_code == 200
    r = await client.get("/api/v1/devices/pg-dev/commands?before=bad", headers=owner)
    assert r.status_code == 422
