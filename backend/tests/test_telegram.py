import pathlib
import sys
from datetime import datetime

import httpx
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "extensions" / "packages" / "fi.valo.telegram"))
import tglogic as tg

from app.db.base import commit, session
from app.domain import ingest

pytestmark = pytest.mark.anyio


def test_recipients_and_pick() -> None:
    rec = tg.parse_recipients("Я=111\nСемья = -100222; 333, мусор=abc")
    assert rec == [("Я", "111"), ("Семья", "-100222"), ("333", "333")]
    assert tg.pick(rec, "") == (["-100222", "111", "333"], [])
    assert tg.pick(rec, "семья, 333") == (["-100222", "333"], [])
    assert tg.pick(rec, "Соседи") == ([], ["Соседи"])
    assert tg.parse_ids("12, x, 34") == {"12", "34"}


def test_recipients_by_name_are_reported_not_dropped_silently() -> None:
    text = "@someone\nСемья=-100222; Сосед=@neighbour, 333"
    assert tg.parse_recipients(text) == [("Семья", "-100222"), ("333", "333")]
    assert tg.rejected_recipients(text) == ["@someone", "Сосед=@neighbour"]
    assert tg.rejected_recipients("Я=111") == []
    assert "/start" in tg.tr("ru", "rejected", list="@someone")


def test_chat_not_found_gets_a_hint() -> None:
    assert "/start" in tg.delivery_hint("uk", "-5400: 400 Bad Request: chat not found")
    assert tg.delivery_hint("en", "429 Too Many Requests") == ""
    assert tg.delivery_hint("de", "chat not found") == tg.tr("en", "not_found")


def test_access_rules() -> None:
    rec = [("Я", "111"), ("Семья", "-100222")]
    assert tg.allowed(111, 111, rec, set())
    assert not tg.allowed(999, 111, rec, set())
    assert tg.allowed(-100222, 5, rec, {"5"})
    assert not tg.allowed(-100222, 6, rec, {"5"})


def test_quiet_and_dedupe() -> None:
    assert tg.quiet("23:00-07:00", datetime(2026, 11, 5, 23, 30))
    assert not tg.quiet("23:00-07:00", datetime(2026, 11, 5, 12, 0))
    assert not tg.quiet("bad", datetime(2026, 11, 5, 23, 30))
    d = tg.Dedupe()
    assert d.allow("a", 10, now=1000)
    assert not d.allow("a", 10, now=1300)
    assert d.allow("a", 10, now=1700)
    assert d.allow("a", 0, now=1701) and d.allow("a", 0, now=1702)


def test_buttons_and_actions(tmp_path) -> None:
    params = {"b1_label": "Выключить", "b1_values": {"on": False}, "b2_label": "", "b2_values": {"on": True}}
    assert tg.buttons(params, {"d": "plug1"}) == [("Выключить", "plug1", {"on": False})]
    assert tg.buttons(params, {}) == []
    acts = tg.Actions(tmp_path / "a.json")
    key = acts.add("plug1", {"on": False}, "Выключить", now=100)
    assert len(f"a:{key}".encode()) <= 64
    again = tg.Actions(tmp_path / "a.json")
    assert again.take(key, now=200)["device"] == "plug1"
    assert again.take(key, now=200) is None
    old = again.add("x", {"on": True}, "On", now=0)
    assert again.take(old, now=tg.Actions.TTL + 1) is None


def test_bot_texts() -> None:
    devs = [
        {"name": "Розетка", "roomId": "k", "available": True, "state": {"on": True, "w": 12.5}},
        {"name": "Протечка", "roomId": None, "available": True, "state": {"leak": True, "bat": 9}},
        {"name": "Лампа", "roomId": "k", "available": False, "state": {}},
    ]
    text = tg.devices_text(devs, [{"id": "k", "name": "Кухня"}], "ru")
    assert "Кухня" in text and "Розетка: включено, 12.5 W" in text and "Лампа: не на связи" in text
    st = tg.status_text("Дом", devs, [{"text": "Протечка, Протечка"}], "ru")
    assert "устройств 3, не на связи 1, тревог 1" in st and "Низкий заряд: Протечка (9%)" in st
    assert tg.tr("xx", "none") == "none"


PLUG = "0xa4c13887ed67a6ba"


async def test_template_variables_in_notify(client: httpx.AsyncClient, owner: dict) -> None:
    item = {
        "ieee_address": PLUG,
        "friendly_name": PLUG,
        "type": "Router",
        "interview_state": "SUCCESSFUL",
        "definition": {
            "vendor": "Zbeacon",
            "model": "TS011F",
            "description": "Розетка",
            "exposes": [{"type": "numeric", "property": "power", "access": 5, "unit": "W"}],
        },
    }
    async with session() as s:
        await ingest.z2m(s, "bridge/devices", [item])
        await ingest.z2m(s, PLUG, {"power": 2500})
        await commit(s)
    room = (await client.post("/api/v1/rooms", json={"name": "Кухня", "floor": 1}, headers=owner)).json()
    await client.patch(f"/api/v1/devices/{PLUG}", json={"roomId": room["id"]}, headers=owner)
    graph = {
        "nodes": [
            {"id": "t", "block": "threshold", "params": {"device": PLUG, "cap": "w", "op": "above", "value": 2000}},
            {"id": "n", "block": "notify", "params": {"text": "{device} в {room}: {value} {unit}, {unknown}"}},
        ],
        "edges": [{"from": "t", "out": 0, "to": "n", "in": 0}],
    }
    fid = (await client.post("/api/v1/flows", json={"name": "Порог", "graph": graph}, headers=owner)).json()["id"]
    res = (await client.post(f"/api/v1/flows/{fid}/test", json={}, headers=owner)).json()
    note = next(x for x in res["trace"] if x["m"] == "dry_notify")
    assert note["p"]["text"] == "Розетка в Кухня: 2500 W, {unknown}"


async def test_list_functions_and_available(client: httpx.AsyncClient, owner: dict) -> None:
    graph = {
        "nodes": [
            {"id": "t", "block": "manual", "params": {}},
            {"id": "c", "block": "expr", "params": {"expr": "low_battery() == 0 and offline() == 0"}},
            {"id": "n", "block": "notify", "params": {"text": "low={low_battery}"}},
        ],
        "edges": [{"from": "t", "out": 0, "to": "c", "in": 0}, {"from": "c", "out": 0, "to": "n", "in": 0}],
    }
    fid = (await client.post("/api/v1/flows", json={"name": "Батарейки", "graph": graph}, headers=owner)).json()["id"]
    res = (await client.post(f"/api/v1/flows/{fid}/test", json={}, headers=owner)).json()
    texts = [x["p"].get("text") for x in res["trace"] if x["m"] == "dry_notify"]
    assert texts == ["low=немає"]


def test_media_ids_and_upload_rules() -> None:
    mid = "3f2b1c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"
    assert tg.media_id(f"/api/v1/media/{mid}/file") == mid
    assert tg.media_id(mid.upper()) == mid
    assert tg.media_id("http://x/api/v1/media/oops/file") is None
    assert tg.flow_media({"snapshot": f"/api/v1/media/{mid}/file", "clip": None}) == mid
    other = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
    assert tg.flow_media({"snapshot": f"/api/v1/media/{mid}/file", "clip": f"/api/v1/media/{other}/file"}) == other
    assert tg.flow_media({"media": mid}) == mid
    assert tg.flow_media({}) is None
    assert tg.upload_method("photo", 500_000) == ("sendPhoto", "photo")
    assert tg.upload_method("photo", tg.PHOTO_MAX + 1) is None
    assert tg.upload_method("video", 40 * 1024 * 1024) == ("sendVideo", "video")
    assert tg.upload_method("video", tg.VIDEO_MAX + 1) is None
    assert tg.upload_method("video", 0) is None
    assert tg.upload_method("other", 10) is None


def test_media_caption_link_and_fallback() -> None:
    assert tg.caption("  Движение  ") == "Движение"
    long = tg.caption("x" * 2000)
    assert len(long) == tg.CAPTION_MAX and long.endswith("...")
    mid = "3f2b1c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"
    assert tg.media_link("http://192.168.0.10:3100/", mid) == f"http://192.168.0.10:3100/api/v1/media/{mid}/file"
    assert tg.media_link("", mid) == ""
    assert tg.media_link("javascript:alert(1)", mid) == ""
    text = tg.fallback_text("ru", "Двор: движение", tg.tr("ru", "too_big", size=61.2), "http://h/x")
    assert text.splitlines()[0] == "Двор: движение"
    assert "61.2 МБ" in text and text.endswith("http://h/x")
    assert tg.fallback_text("en", "", "", "").endswith("Cameras section")


def test_media_multipart_and_clip_wait() -> None:
    body, kind = tg.multipart({"chat_id": "-100", "caption": "Двор"}, "photo", "a.jpg", b"\xff\xd8data", "image/jpeg")
    boundary = kind.split("boundary=", 1)[1]
    assert kind.startswith("multipart/form-data")
    assert body.startswith(f"--{boundary}\r\n".encode()) and body.endswith(f"--{boundary}--\r\n".encode())
    assert 'name="caption"\r\n\r\nДвор'.encode() in body
    assert b'name="photo"; filename="a.jpg"\r\nContent-Type: image/jpeg\r\n\r\n\xff\xd8data' in body
    since = datetime(2026, 11, 7, 10, 0, 0).astimezone().timestamp()
    items = [
        {"id": "old", "kind": "video", "origin": "ext:fi.valo.telegram", "createdAt": "2026-11-07T07:00:00+00:00"},
        {"id": "ev", "kind": "video", "origin": "event", "createdAt": "2099-01-01T00:00:00+00:00"},
        {"id": "ph", "kind": "photo", "origin": "ext:fi.valo.telegram", "createdAt": "2099-01-01T00:00:00+00:00"},
        {"id": "new", "kind": "video", "origin": "ext:fi.valo.telegram", "createdAt": "2099-01-01T00:00:00+00:00"},
    ]
    assert tg.clip_ready(items, since, "ext:fi.valo.telegram")["id"] == "new"
    assert tg.clip_ready(items[:3], since, "ext:fi.valo.telegram") is None
    assert tg.clip_ready([{"kind": "video", "origin": "x", "createdAt": "bad"}], since, "x") is None
