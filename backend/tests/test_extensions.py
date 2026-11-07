import json

import httpx
import pytest

from app.db.base import commit, session
from app.db.models import Extension
from app.domain import extensions
from app.lib.errors import ApplicationError
from app.lib.kv import kv

pytestmark = pytest.mark.anyio
TG_OLD = ["network.outbound:api.telegram.org", "notifications.send"]
TG_NEW = ["devices.read", "devices.control", "media.read", "media.write"]


async def test_catalog_lists_packages(client: httpx.AsyncClient, owner: dict) -> None:
    r = await client.get("/api/v1/extensions/catalog", headers=owner)
    assert r.status_code == 200
    ids = {e["id"] for e in r.json()}
    assert {"fi.valo.energy", "fi.valo.telegram", "dev.local.simulator"} <= ids


async def test_install_requires_grants(client: httpx.AsyncClient, owner: dict) -> None:
    ps = kv().pubsub()
    await ps.subscribe("ext:cmd")
    r = await client.post("/api/v1/extensions/fi.valo.telegram/install", json={"grants": []}, headers=owner)
    assert r.status_code == 422 and r.json()["code"] == "ext_grants"
    perms = [*TG_OLD, "devices.read", "devices.control", "media.read", "media.write"]
    r = await client.post("/api/v1/extensions/fi.valo.telegram/install", json={"grants": perms}, headers=owner)
    assert r.status_code == 202, r.text
    assert r.json()["status"] == "installing"
    again = await client.post("/api/v1/extensions/fi.valo.telegram/install", json={"grants": perms}, headers=owner)
    assert again.status_code == 409
    msg = None
    for _ in range(20):
        msg = await ps.get_message(ignore_subscribe_messages=True, timeout=0.2)
        if msg:
            break
    assert msg and json.loads(msg["data"]) == {"op": "install", "id": "fi.valo.telegram"}
    await ps.aclose()


async def test_core_call_permissions(client: httpx.AsyncClient, owner: dict) -> None:
    async with session() as s:
        s.add(
            Extension(
                id="test.ext",
                name="Test",
                version="1.0.0",
                trust="local",
                status="running",
                enabled=True,
                manifest={},
                settings={},
                grants=["notifications.send"],
                restarts=0,
            )
        )
        await commit(s)
    async with session() as s:
        home = await extensions.core_call(s, "test.ext", "home", {})
        assert home["timezone"] == "Europe/Helsinki"
        with pytest.raises(ApplicationError) as e:
            await extensions.core_call(s, "test.ext", "devices.list", {})
        assert e.value.code == "ext_permission"
        assert await extensions.core_call(s, "test.ext", "notify", {"text": "hello", "level": "warn"}) == {"ok": True}
        await extensions.core_call(s, "test.ext", "event", {"text": "report"})
        await commit(s)
    notes = (await client.get("/api/v1/notifications", headers=owner)).json()
    assert any(n["params"].get("text") == "hello" for n in notes)
    evs = (await client.get("/api/v1/events", headers=owner)).json()
    assert any(ev["type"] == "ext.event" and ev["params"]["text"] == "report" for ev in evs)
    async with session() as s:
        x = await s.get(Extension, "test.ext")
        x.status = "stopped"
        await commit(s)
    async with session() as s:
        with pytest.raises(ApplicationError) as e:
            await extensions.core_call(s, "test.ext", "home", {})
        assert e.value.code == "forbidden"


async def test_update_asks_for_new_permissions(client: httpx.AsyncClient, owner: dict) -> None:
    old = TG_OLD
    r = await client.post(
        "/api/v1/extensions/fi.valo.telegram/install", json={"grants": old, "version": "2.0.1"}, headers=owner
    )
    assert r.status_code == 202, r.text
    async with session() as s:
        x = await s.get(Extension, "fi.valo.telegram")
        x.status = "running"
        await commit(s)
    ext = (await client.get("/api/v1/extensions/fi.valo.telegram", headers=owner)).json()
    assert ext["update"] == "3.1.0" and ext["newPerms"] == TG_NEW
    r = await client.post("/api/v1/extensions/fi.valo.telegram/update", json={}, headers=owner)
    assert r.status_code == 422 and r.json()["code"] == "ext_grants"
    r = await client.post(
        "/api/v1/extensions/fi.valo.telegram/update",
        json={"grants": TG_NEW},
        headers=owner,
    )
    assert r.status_code == 202, r.text
    assert set(r.json()["grants"]) == {*old, *TG_NEW}


async def test_secret_sealed_masked_and_cleared(client: httpx.AsyncClient, owner: dict) -> None:
    perms = [*TG_OLD, "devices.read", "devices.control", "media.read", "media.write"]
    await client.post("/api/v1/extensions/fi.valo.telegram/install", json={"grants": perms}, headers=owner)
    url = "/api/v1/extensions/fi.valo.telegram/settings"
    r = await client.patch(url, json={"values": {"token": "123:ABC", "recipients": "Я=1"}}, headers=owner)
    assert r.status_code == 200 and r.json()["settings"]["token"] == "" and r.json()["secrets"] == ["token"]
    async with session() as s:
        x = await s.get(Extension, "fi.valo.telegram")
        assert x.settings["token"].startswith("enc1:")
        assert extensions.plain_settings(x)["token"] == "123:ABC"
    r = await client.patch(url, json={"values": {"token": ""}}, headers=owner)
    assert r.json()["secrets"] == ["token"]
    r = await client.patch(url, json={"values": {"token": None}}, headers=owner)
    assert r.json()["secrets"] == []


async def test_removed_extension_devices_do_not_come_back(
    client: httpx.AsyncClient, owner: dict, published: list
) -> None:
    from app.db.models import Device
    from app.domain import ingest

    meta = {"name": "Price", "kind": "price", "caps": [{"id": "p", "type": "num", "access": "r"}]}
    async with session() as s:
        assert await ingest.hub(s, "hub/v1/ext/gone.ext/dev/price/meta", meta)
        await commit(s)
        assert await s.get(Device, "ext-price") is None
        s.add(
            Extension(
                id="gone.ext",
                name="Gone",
                version="1.0.0",
                trust="official",
                status="running",
                enabled=True,
                manifest={},
                settings={},
                grants=["devices.virtual"],
                restarts=0,
            )
        )
        await commit(s)
        await ingest.hub(s, "hub/v1/ext/gone.ext/dev/price/meta", meta)
        await commit(s)
        assert await s.get(Device, "ext-price") is not None
        await extensions.purge(s, "gone.ext")
        await commit(s)
        assert await s.get(Device, "ext-price") is None
    cleared = {t for t, p in published if p == b""}
    assert {f"hub/v1/ext/gone.ext/dev/price/{x}" for x in ("meta", "state", "avail")} <= cleared
    async with session() as s:
        await ingest.hub(s, "hub/v1/ext/gone.ext/dev/price/meta", meta)
        await commit(s)
        assert await s.get(Device, "ext-price") is None


async def test_extension_cannot_write_to_another_extension_device(client: httpx.AsyncClient, owner: dict) -> None:
    from app.db.models import Device
    from app.domain import ingest

    meta = {"name": "Usage", "kind": "meter", "caps": [{"id": "w", "type": "num", "access": "r"}]}
    async with session() as s:
        for ext_id in ("a.energy", "b.energy"):
            s.add(
                Extension(
                    id=ext_id,
                    name=ext_id,
                    version="1.0.0",
                    trust="official",
                    status="running",
                    enabled=True,
                    manifest={},
                    settings={},
                    grants=["devices.virtual"],
                    restarts=0,
                )
            )
        await commit(s)
        await ingest.hub(s, "hub/v1/ext/a.energy/dev/usage/meta", meta)
        await ingest.hub(s, "hub/v1/ext/a.energy/dev/usage/state", {"w": 100})
        await commit(s)
        await ingest.hub(s, "hub/v1/ext/b.energy/dev/usage/state", {"w": 999})
        await ingest.hub(s, "hub/v1/ext/b.energy/dev/usage/meta", {**meta, "name": "Hijack"})
        await ingest.hub(s, "hub/v1/ext/b.energy/dev/usage/meta", {})
        await commit(s)
        d = await s.get(Device, "energy-usage")
        assert d is not None and d.ext_id == "a.energy" and d.state["w"] == 100 and d.name == "Usage"


async def test_extension_change_notice_reaches_all_users(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.lib import realtime
    from app.mqtt import main as mq

    sent: list = []

    async def fake(event: str, data: object, rooms: list[str], durable: bool = True) -> None:
        sent.append((event, data, rooms, durable))

    monkeypatch.setattr(realtime, "emit", fake)
    await mq.ext_message("fi.valo.energy", "changed", None, {"keys": ["usage", "today", 5, "x" * 80]})
    await mq.ext_message("fi.valo.energy", "changed", None, {"keys": "usage"})
    await mq.ext_message("fi.valo.energy", "log", None, "ready")
    assert sent == [
        ("ext_page", {"ext": "fi.valo.energy", "keys": ["usage", "today"]}, ["any"], False),
        ("ext_log", {"ext": "fi.valo.energy", "line": "ready"}, ["extlog:fi.valo.energy"], False),
    ]


async def test_page_actions_need_member_and_get_the_real_role(
    client: httpx.AsyncClient, owner: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.server import admin

    seen: list[dict] = []

    async def fake_rpc(s: object, ext_id: str, method: str, params: dict) -> dict:
        seen.append({"ext": ext_id, "method": method, **params})
        return {"blocks": []}

    monkeypatch.setattr(admin.extensions, "rpc", fake_rpc)
    r = await client.post(
        "/api/v1/users",
        json={"username": "vieras", "name": "Vieras", "password": "secret123", "role": "guest"},
        headers=owner,
    )
    assert r.status_code == 201, r.text
    r = await client.post("/api/v1/auth/login", json={"username": "vieras", "password": "secret123"})
    guest = {"Authorization": f"Bearer {r.json()['token']}"}
    url = "/api/v1/extensions/fi.valo.safety/page/safety"
    assert (await client.post(url, json={"lang": "en", "role": "owner"}, headers=guest)).status_code in (200, 201)
    assert seen[-1]["role"] == "guest" and seen[-1]["method"] == "page.safety"
    assert (await client.post(url, json={"action": "disarm"}, headers=guest)).status_code == 403
    assert len(seen) == 1
    assert (await client.post(url, json={"action": "disarm"}, headers=owner)).status_code in (200, 201)
    assert seen[-1] == {"ext": "fi.valo.safety", "method": "page.safety", "action": "disarm", "role": "owner"}


def test_extension_declares_service_or_device_and_kind_is_the_fallback() -> None:
    from app.domain.devices import is_service

    assert is_service("ext", "safety", True) and not is_service("ext", "weather", False)
    assert is_service("ext", "weather") and not is_service("ext", "clim")
    assert is_service("ext", "weather", "yes") and not is_service("ext", "clim", 1)
    assert not is_service("zigbee", "weather", True) and not is_service("mqtt", "meter")
