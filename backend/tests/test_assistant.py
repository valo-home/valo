import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest

from app.agent import main as agent
from app.db.base import commit, session
from app.db.models import AiSettings, ChatAction, Dashboard, Device
from app.domain import assistant, ingest
from app.domain import assistant_tools as tools
from app.domain.common import Principal
from app.lib import llm
from app.lib.kv import kv

pytestmark = pytest.mark.anyio


class Script:
    """Подставная модель: каждый вызов stream отдает следующий заранее заданный ответ."""

    def __init__(self, replies: list[llm.Reply]) -> None:
        self.replies = replies
        self.seen: list[list[dict[str, Any]]] = []
        self.tools: list[list[dict[str, Any]] | None] = []

    async def __call__(self, cfg: llm.Config, messages: list[dict[str, Any]], specs: Any = None) -> AsyncIterator[Any]:
        self.seen.append(list(messages))
        self.tools.append(specs)
        r = self.replies.pop(0)
        if r.text:
            yield r.text
        yield r


def call(name: str, args: dict[str, Any], cid: str = "c1") -> llm.Call:
    return llm.Call(id=cid, name=name, arguments=json.dumps(args))


async def enable(client: httpx.AsyncClient, owner: dict) -> None:
    r = await client.patch(
        "/api/v1/ai/settings", json={"enabled": True, "apiKey": "sk-test-key", "model": "test/model"}, headers=owner
    )
    assert r.status_code == 200, r.text
    assert r.json()["keySet"] is True and "apiKey" not in r.json()


async def plug() -> None:
    meta = {
        "name": "Розетка",
        "kind": "plug",
        "caps": [
            {"id": "on", "type": "bool", "access": "rw"},
            {"id": "v", "type": "num", "access": "r", "unit": "V"},
            {"id": "w", "type": "num", "access": "r", "unit": "W"},
        ],
    }
    async with session() as s:
        await ingest.hub(s, "hub/v1/dev/plug-1/meta", meta)
        await ingest.hub(s, "hub/v1/dev/plug-1/state", {"on": False, "v": 231, "w": 0})
        await commit(s)


async def new_chat(client: httpx.AsyncClient, owner: dict, text: str) -> tuple[str, dict]:
    chat = (await client.post("/api/v1/chats", json={}, headers=owner)).json()
    r = await client.post(f"/api/v1/chats/{chat['id']}/messages", json={"text": text}, headers=owner)
    assert r.status_code == 202, r.text
    job = json.loads(await kv().rpop(assistant.JOBS))
    return chat["id"], job


async def test_settings_are_admin_only_and_key_is_sealed(client: httpx.AsyncClient, owner: dict) -> None:
    assert (await client.get("/api/v1/ai/status", headers=owner)).json() == {
        "enabled": False,
        "ready": False,
        "model": "deepseek/deepseek-v4.1-flash",
    }
    await enable(client, owner)
    async with session() as s:
        row = await s.get(AiSettings, 1)
        assert row.api_key.startswith("enc1:") and "sk-test-key" not in row.api_key
    assert (await client.get("/api/v1/ai/status", headers=owner)).json()["ready"] is True
    await client.post(
        "/api/v1/users",
        json={"username": "aino", "name": "Aino", "password": "secret123", "role": "member"},
        headers=owner,
    )
    tok = (await client.post("/api/v1/auth/login", json={"username": "aino", "password": "secret123"})).json()["token"]
    member = {"Authorization": f"Bearer {tok}"}
    assert (await client.get("/api/v1/ai/settings", headers=member)).status_code == 403
    bad = await client.patch("/api/v1/ai/settings", json={"baseUrl": "ftp://x"}, headers=owner)
    assert bad.status_code == 422
    cleared = await client.patch("/api/v1/ai/settings", json={"apiKey": None}, headers=owner)
    assert cleared.json()["keySet"] is False


async def test_chats_belong_to_their_user(client: httpx.AsyncClient, owner: dict) -> None:
    r = await client.post("/api/v1/chats", json={}, headers=owner)
    cid = r.json()["id"]
    assert (await client.post(f"/api/v1/chats/{cid}/messages", json={"text": "hi"}, headers=owner)).status_code == 409
    await client.post(
        "/api/v1/users",
        json={"username": "aino", "name": "Aino", "password": "secret123", "role": "admin"},
        headers=owner,
    )
    tok = (await client.post("/api/v1/auth/login", json={"username": "aino", "password": "secret123"})).json()["token"]
    other = {"Authorization": f"Bearer {tok}"}
    assert (await client.get(f"/api/v1/chats/{cid}", headers=other)).status_code == 404
    assert (await client.get("/api/v1/chats", headers=other)).json() == []
    assert (await client.patch(f"/api/v1/chats/{cid}", json={"title": "Мой"}, headers=owner)).json()["title"] == "Мой"
    assert (await client.delete(f"/api/v1/chats/{cid}", headers=owner)).status_code == 204
    assert (await client.get(f"/api/v1/chats/{cid}", headers=owner)).status_code == 404


async def test_agent_builds_dashboard_and_user_can_undo(
    client: httpx.AsyncClient, owner: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    await enable(client, owner)
    await plug()
    cid, job = await new_chat(client, owner, "Сделай панель с напряжением розетки")
    widgets = [
        {"type": "chart", "device": "plug-1", "cap": "v", "hours": 24, "size": "wide"},
        {"type": "plug", "device": "plug-1"},
    ]
    script = Script(
        [
            llm.Reply(calls=[call("get_device", {"device_id": "plug-1"}, "c0")], usage={"total": 10}),
            llm.Reply(
                calls=[call("create_dashboard", {"name": "Розетка", "widgets": widgets}, "c1")], usage={"total": 20}
            ),
            llm.Reply(text="Готово, панель **Розетка** создана", usage={"total": 5}),
        ]
    )
    monkeypatch.setattr(llm, "stream", script)
    await agent.turn(job)
    assert "Сделай панель" in script.seen[0][-1]["content"] and script.seen[0][0]["role"] == "system"
    assert script.seen[2][-1]["role"] == "tool" and '"ok": true' in script.seen[2][-1]["content"]
    async with session() as s:
        b = await s.get(Dashboard, "rozetka")
        assert b is not None and [w["type"] for w in b.widgets] == ["chart", "plug"] and b.widgets[0]["cap"] == "v"
    d = (await client.get(f"/api/v1/chats/{cid}", headers=owner)).json()
    assert (
        d["chat"]["status"] == "idle" and d["chat"]["tokens"] == 35 and d["chat"]["title"].startswith("Сделай панель")
    )
    roles = [m["role"] for m in d["messages"]]
    assert roles == ["user", "assistant", "tool", "assistant", "tool", "assistant"]
    assert d["messages"][-1]["content"].startswith("Готово")
    act = d["actions"][0]
    assert act["tool"] == "create_dashboard" and act["status"] == "done" and act["canUndo"] is True
    r = await client.post(f"/api/v1/chats/{cid}/actions/{act['id']}/undo", headers=owner)
    assert r.json()["status"] == "undone"
    async with session() as s:
        assert await s.get(Dashboard, "rozetka") is None
    assert (await client.post(f"/api/v1/chats/{cid}/actions/{act['id']}/undo", headers=owner)).status_code == 409


async def test_device_command_waits_for_confirmation(
    client: httpx.AsyncClient, owner: dict, monkeypatch: pytest.MonkeyPatch, published: list
) -> None:
    await enable(client, owner)
    await plug()
    cid, job = await new_chat(client, owner, "Включи розетку")
    script = Script(
        [
            llm.Reply(calls=[call("device_command", {"device_id": "plug-1", "values": {"on": True}})]),
            llm.Reply(text="Нажмите Выполнить"),
        ]
    )
    monkeypatch.setattr(llm, "stream", script)
    await agent.turn(job)
    assert not any(t == "hub/v1/dev/plug-1/set" for t, _ in published)
    assert "waiting_for_user" in script.seen[1][-1]["content"]
    act = (await client.get(f"/api/v1/chats/{cid}", headers=owner)).json()["actions"][0]
    assert act["status"] == "pending" and "Розетка" in act["summary"]
    r = await client.post(f"/api/v1/chats/{cid}/actions/{act['id']}/confirm", headers=owner)
    assert r.json()["status"] == "done", r.text
    assert r.json()["result"]["value"]["deviceId"] == "plug-1"
    assert any(t == "hub/v1/dev/plug-1/set" and p["values"] == {"on": True} for t, p in published)
    notes = [
        m for m in (await client.get(f"/api/v1/chats/{cid}", headers=owner)).json()["messages"] if m["role"] == "note"
    ]
    assert notes[-1]["data"]["kind"] == "confirmed"
    assert (await client.post(f"/api/v1/chats/{cid}/actions/{act['id']}/confirm", headers=owner)).status_code == 409


async def test_tool_errors_and_guest_limits(client: httpx.AsyncClient, owner: dict) -> None:
    await plug()
    guest = Principal(id="00000000-0000-7000-8000-000000000001", username="g", name="Guest", role="guest")
    names = {t["function"]["name"] for t in tools.specs(guest)}
    assert "list_devices" in names and "create_dashboard" not in names and "device_command" not in names
    async with session() as s:
        text, meta = await assistant.run_tool(s, guest, "00000000-0000-7000-8000-000000000002", "create_room", "{}")
        assert meta == {"ok": False} and "unknown_tool" in text
        owner_p = Principal(id="00000000-0000-7000-8000-000000000003", username="o", name="O", role="owner")
        bad = [{"type": "chart", "device": "plug-1", "cap": "nope"}]
        ctx = tools.Ctx(s=s, p=owner_p, lang="ru")
        with pytest.raises(assistant.ApplicationError):
            await tools.validate_widgets(ctx, bad)
        with pytest.raises(assistant.ApplicationError):
            await tools.validate_widgets(ctx, [{"type": "nope"}])
        ok = await tools.validate_widgets(ctx, [{"type": "value", "device": "plug-1", "cap": "w"}, {"type": "clock"}])
        assert [w["type"] for w in ok] == ["value", "clock"] and all(w["id"] for w in ok)
        restricted = Principal(id=owner_p.id, username="r", name="R", role="member", rooms=["kitchen"])
        assert "list_flows" not in {t["function"]["name"] for t in tools.specs(restricted)}


async def test_source_reader_stays_inside_source(
    client: httpx.AsyncClient, owner: dict, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "x.py").write_text("a = 1\nb = 2\n")
    (tmp_path.parent / "secret.txt").write_text("nope")
    monkeypatch.setattr(tools, "SRC_DIR", tmp_path)
    admin = Principal(id="00000000-0000-7000-8000-000000000003", username="o", name="O", role="admin")
    async with session() as s:
        ctx = tools.Ctx(s=s, p=admin, lang="en")
        assert (await tools.t_read_source(ctx, {"path": "app/x.py"}))["text"] == "1: a = 1\n2: b = 2"
        for path in ("../secret.txt", "/etc/passwd", "app/../../secret.txt"):
            with pytest.raises(assistant.ApplicationError):
                await tools.t_read_source(ctx, {"path": path})
        member = Principal(id=admin.id, username="m", name="M", role="member")
        with pytest.raises(assistant.ApplicationError):
            await tools.t_read_source(tools.Ctx(s=s, p=member, lang="en"), {"path": "app/x.py"})


async def test_model_errors_end_the_turn_with_a_message(
    client: httpx.AsyncClient, owner: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    await enable(client, owner)
    cid, job = await new_chat(client, owner, "Привет")

    async def broken(cfg: llm.Config, messages: Any, specs: Any = None) -> AsyncIterator[Any]:
        raise llm.LlmError("llm_auth", "bad key", 401)
        yield

    monkeypatch.setattr(llm, "stream", broken)
    await agent.turn(job)
    d = (await client.get(f"/api/v1/chats/{cid}", headers=owner)).json()
    assert d["chat"]["status"] == "idle" and d["messages"][-1]["data"]["error"] == "llm_auth"


async def test_history_drops_orphan_tool_results() -> None:
    from app.db.models import ChatMessage

    rows = [
        ChatMessage(role="user", content="a", data={}),
        ChatMessage(role="tool", content="x", data={"tool_call_id": "zz"}),
        ChatMessage(
            role="assistant", content="", data={"tool_calls": [{"id": "c1", "name": "list_rooms", "arguments": "{}"}]}
        ),
        ChatMessage(role="tool", content="[]", data={"tool_call_id": "c1"}),
        ChatMessage(role="note", content="User declined", data={"kind": "rejected"}),
    ]
    out = assistant.to_llm(rows)
    assert [m["role"] for m in out] == ["user", "assistant", "tool", "user"]
    assert out[-1]["content"].startswith("[Valo]")


async def test_ws_chat_room_is_only_for_owner(client: httpx.AsyncClient, owner: dict) -> None:
    from app.ws import main as ws

    cid = (await client.post("/api/v1/chats", json={}, headers=owner)).json()["id"]
    me = (await client.get("/api/v1/auth/me", headers=owner)).json()
    mine = Principal(id=me["id"], username="mikko", name="M", role="owner")
    other = Principal(id="00000000-0000-7000-8000-0000000000aa", username="x", name="X", role="owner")
    assert await ws._allowed(mine, f"chat:{cid}")
    assert not await ws._allowed(other, f"chat:{cid}")
    assert not await ws._allowed(mine, "chat:not-a-uuid")


async def test_overview_counts_physical_devices_and_lists_services_apart(client: httpx.AsyncClient) -> None:
    await plug()
    async with session() as s:
        if await s.get(Device, "openmeteo-weather") is None:
            s.add(
                Device(
                    id="openmeteo-weather", name="Open-Meteo", source="ext", kind="weather", ext_id="fi.valo.weather"
                )
            )
        if await s.get(Device, "sim-motion") is None:
            s.add(Device(id="sim-motion", name="Sim motion", source="ext", kind="motion", ext_id="dev.local.simulator"))
        await commit(s)
    owner_p = Principal(id="00000000-0000-7000-8000-000000000003", username="o", name="O", role="owner")
    async with session() as s:
        o = await tools.t_overview(tools.Ctx(s=s, p=owner_p, lang="ru"), {})
        listed = await tools.t_list_devices(tools.Ctx(s=s, p=owner_p, lang="ru"), {})
    physical = [d for d in listed["devices"] if not d["source"].startswith("service")]
    assert o["devices"] == len(physical) == sum(o["bySource"].values())
    assert {"plug-1", "sim-motion"} <= {d["id"] for d in physical}
    assert [x["name"] for x in o["services"]] == ["Open-Meteo"]
    assert "Open-Meteo" not in o["unassigned"]
    sources = {d["id"]: d["source"] for d in listed["devices"]}
    assert sources["openmeteo-weather"] == "service fi.valo.weather"
    prompt = tools.system_prompt("Дом", "ru", owner_p, "2026-11-06 10:00")
    assert '"Выполнить"' in prompt and '"Отменить"' in prompt and "Execute" not in prompt


async def test_action_note_waits_for_turn_end_and_sends_current_status(
    client: httpx.AsyncClient, owner: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.lib import realtime

    await enable(client, owner)
    await plug()
    cid, _ = await new_chat(client, owner, "Включи розетку")
    async with session() as s:
        a = ChatAction(
            chat_id=uuid.UUID(cid), tool="device_command", args={"device_id": "plug-1", "values": {"on": True}}
        )
        s.add(a)
        await commit(s)
        aid = str(a.id)
    sent: list = []

    async def fake(event: str, data: object, rooms: list[str], durable: bool = True) -> None:
        sent.append((event, data))

    monkeypatch.setattr(realtime, "emit", fake)
    async with session() as ending:
        await assistant.finish(ending, cid, 0)
        click = asyncio.create_task(client.post(f"/api/v1/chats/{cid}/actions/{aid}/reject", headers=owner))
        await asyncio.sleep(0.3)
        assert not click.done()
        await commit(ending)
    assert (await click).json()["status"] == "rejected"
    chats = [d for e, d in sent if e == "chat"]
    assert [c.status for c in chats] == ["idle", "idle"]
    assert chats[-1].updated_at >= chats[0].updated_at
