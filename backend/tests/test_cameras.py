import os
import pathlib
import sys
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import select

from app.db.base import commit, now, session
from app.db.models import Camera, CameraEvent, Device, Extension, Media
from app.domain import blocks, cameras, extensions, flows, media
from app.lib import rtc
from app.lib.errors import ApplicationError

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "extensions" / "sdk"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "extensions" / "packages" / "fi.valo.thingino"))
import thinglogic as tl
import valo_camera as vc

SDK = pathlib.Path(__file__).resolve().parents[2] / "extensions"

pytestmark = pytest.mark.anyio
DRIVER = "test.cam"
FIELDS = [
    {"key": "host", "type": "text", "required": True, "default": ""},
    {"key": "password", "type": "secret", "default": ""},
    {"key": "fps", "type": "number", "default": 10},
]


async def add_ext(ext_id: str, grants: list[str], camera: bool = True) -> None:
    async with session() as s:
        s.add(
            Extension(
                id=ext_id,
                name=ext_id,
                version="1.0.0",
                trust="local",
                status="running",
                enabled=True,
                manifest={
                    "name": {"en": "Test cam"},
                    **({"camera": {"fields": FIELDS, "features": list(cameras.FEATURES)}} if camera else {}),
                },
                settings={},
                grants=grants,
                restarts=0,
            )
        )
        await commit(s)


@pytest.fixture
async def driver(client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    calls: list[dict] = []

    async def fake_rpc(s: object, ext_id: str, method: str, params: dict, timeout: float = 10) -> dict:
        calls.append({"ext": ext_id, "method": method, **params})
        if method == "camera.probe":
            pw = params["config"].get("password", "")
            return {
                "streams": {"main": f"rtsp://u:{pw}@{params['config']['host']}/ch0", "sub": "rtsp://u:x@h/ch1"},
                "stills": {"snapshot": "http://h/x/ch0.jpg?token=k", "bad": "file:///etc/passwd"},
                "info": {"model": "T1", "vendor": "Test", "nested": {"no": 1}},
                "caps": [{"id": "night", "type": "bool", "access": "rw"}],
            }
        return {"ok": True}

    monkeypatch.setattr(cameras.extensions, "rpc", fake_rpc)
    await add_ext(DRIVER, ["cameras.provide"])
    return calls


async def guest_headers(client: httpx.AsyncClient, owner: dict) -> dict:
    r = await client.post(
        "/api/v1/users",
        json={"username": "vieras", "name": "Vieras", "password": "secret123", "role": "guest"},
        headers=owner,
    )
    assert r.status_code == 201, r.text
    r = await client.post("/api/v1/auth/login", json={"username": "vieras", "password": "secret123"})
    return {"Authorization": f"Bearer {r.json()['token']}"}


async def test_camera_is_a_device_with_sealed_secrets(client: httpx.AsyncClient, owner: dict, driver: list) -> None:
    r = await client.get("/api/v1/cameras/drivers", headers=owner)
    assert [d["id"] for d in r.json()] == [DRIVER]
    body = {"driver": DRIVER, "name": "Прихожая", "config": {"host": "10.0.0.5", "password": "p@ss"}}
    r = await client.post("/api/v1/cameras", json=body, headers=owner)
    assert r.status_code == 201, r.text
    cam = r.json()
    assert cam["id"] == "prihozhaya" and cam["deviceId"] == "cam-prihozhaya"
    assert cam["config"] == {"host": "10.0.0.5"} and cam["secrets"] == ["password"]
    assert cam["streams"] == ["main", "sub"] and cam["stills"] == ["snapshot"]
    assert cam["info"] == {"model": "T1", "vendor": "Test"}
    assert driver[0]["method"] == "camera.probe" and driver[0]["config"]["password"] == "p@ss"
    async with session() as s:
        c = await s.get(Camera, "prihozhaya")
        d = await s.get(Device, "cam-prihozhaya")
        assert c.config["password"].startswith("enc1:") and "p@ss" not in str(c.streams)
        assert d.kind == "camera" and d.source == "ext" and d.ext_id == DRIVER and d.address == "prihozhaya"
        assert [x["id"] for x in d.caps] == ["occ", "night"]
        src = await cameras.sources(s)
        assert src["prihozhaya"]["main"] == "rtsp://u:p@ss@10.0.0.5/ch0"
        mine = await extensions.core_call(s, DRIVER, "cameras.mine", {})
        assert mine == [
            {
                "id": "prihozhaya",
                "config": {"host": "10.0.0.5", "password": "p@ss"},
                "info": {"model": "T1", "vendor": "Test"},
            }
        ]
    r = await client.post("/api/v1/cameras", json={**body, "name": "Двор", "config": {}}, headers=owner)
    assert r.status_code == 422 and r.json()["code"] == "camera_field_required"
    r = await client.patch(
        "/api/v1/cameras/prihozhaya", json={"record": {"mode": "off", "pre": 99}, "name": "Вход"}, headers=owner
    )
    assert r.status_code == 200 and r.json()["record"]["mode"] == "off" and r.json()["record"]["pre"] == 30
    probes = [c for c in driver if c["method"] == "camera.probe"]
    assert r.json()["name"] == "Вход" and len(probes) == 1
    assert driver[-1]["method"] == "camera.sync"
    r = await client.patch(
        "/api/v1/cameras/prihozhaya", json={"config": {"host": "10.0.0.6", "password": "", "fps": "12"}}, headers=owner
    )
    probes = [c for c in driver if c["method"] == "camera.probe"]
    assert r.status_code == 200 and probes[-1]["config"] == {"host": "10.0.0.6", "password": "p@ss", "fps": 12.0}
    guest = await guest_headers(client, owner)
    assert (await client.get("/api/v1/cameras", headers=guest)).status_code == 403
    assert (await client.get("/api/v1/cameras/prihozhaya/preview", headers=guest)).status_code == 403
    assert (await client.delete("/api/v1/cameras/prihozhaya", headers=owner)).status_code == 204
    async with session() as s:
        assert await s.get(Camera, "prihozhaya") is None and await s.get(Device, "cam-prihozhaya") is None


async def test_events_open_close_and_need_permission(client: httpx.AsyncClient, owner: dict, driver: list) -> None:
    r = await client.post(
        "/api/v1/cameras", json={"driver": DRIVER, "name": "Yard", "config": {"host": "h"}}, headers=owner
    )
    assert r.status_code == 201
    await add_ext("other.ext", [])
    await add_ext("detector", ["cameras.events"], camera=False)
    async with session() as s:
        a = await extensions.core_call(s, DRIVER, "cameras.event", {"camera": "yard", "active": True})
        b = await extensions.core_call(s, DRIVER, "cameras.event", {"camera": "yard", "active": True, "score": 0.5})
        assert a["event"] == b["event"]
        with pytest.raises(ApplicationError) as e:
            await extensions.core_call(s, "other.ext", "cameras.event", {"camera": "yard", "active": True})
        assert e.value.code == "ext_permission"
        person = {"camera": "yard", "label": "person", "active": True}
        await extensions.core_call(s, "detector", "cameras.event", person)
        await commit(s)
        d = await s.get(Device, "cam-yard")
        assert d.state["occ"] is True and d.state["person"] is True and any(c["id"] == "person" for c in d.caps)
        await extensions.core_call(s, "detector", "cameras.event", {**person, "active": False})
        await extensions.core_call(s, "detector", "cameras.event", {"camera": "yard", "label": "car", "active": None})
        await extensions.core_call(s, DRIVER, "cameras.event", {"camera": "yard", "active": False})
        await commit(s)
    async with session() as s:
        evs = (await s.scalars(select(CameraEvent).order_by(CameraEvent.id))).all()
        assert [(e.label, e.source, e.ended_at is not None) for e in evs] == [
            ("motion", "driver", True),
            ("person", "ext:detector", True),
            ("car", "ext:detector", True),
        ]
        assert evs[0].score == 0.5
        assert (await s.get(Device, "cam-yard")).state["occ"] is False
        evs[0].ended_at, evs[0].started_at = None, now() - timedelta(seconds=cameras.STALE + 5)
        await commit(s)
        assert await cameras.close_stale(s) == 1
    r = await client.get("/api/v1/cameras/yard/events", headers=owner)
    assert [e["label"] for e in r.json()] == ["car", "person", "motion"]


async def test_rtc_access_is_limited_to_known_streams(client: httpx.AsyncClient, owner: dict, driver: list) -> None:
    await client.post(
        "/api/v1/cameras", json={"driver": DRIVER, "name": "Gate", "config": {"host": "h"}}, headers=owner
    )
    ok = {**owner, "X-Forwarded-Uri": "/rtc/api/ws?src=gate_sub"}
    r = await client.get("/api/v1/cameras/rtc-auth", headers=ok)
    assert r.status_code == 200 and r.headers["authorization"] == rtc.auth_header()
    for uri in ("/rtc/api/streams", "/rtc/api/ws?src=../x", "/rtc/api/ws", "/api/v1/x"):
        r = await client.get("/api/v1/cameras/rtc-auth", headers={**owner, "X-Forwarded-Uri": uri})
        assert r.status_code == 403, uri
    r = await client.get("/api/v1/cameras/rtc-auth", headers={**owner, "X-Forwarded-Uri": "/rtc/api/ws?src=nope"})
    assert r.status_code == 404
    assert (
        await client.get("/api/v1/cameras/rtc-auth", headers={"X-Forwarded-Uri": "/rtc/api/ws?src=gate"})
    ).status_code == 401
    assert rtc.mask("rtsp://u:secret@h/ch0") == "rtsp://***@h/ch0"


async def test_storage_rotates_oldest_and_stops_video_when_full(
    client: httpx.AsyncClient, owner: dict, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MEDIA_DIR", str(tmp_path))
    free = {"v": 5 * media.GB}
    monkeypatch.setattr(media, "disk", lambda p: {"free": free["v"], "total": 100 * media.GB})
    with pytest.raises(ApplicationError):
        media.inside("../etc")
    assert media.inside("a/b") == tmp_path.resolve() / "a" / "b"
    r = await client.patch("/api/v1/media/storage", json={"dir": "rec", "minFreeGb": 10, "days": 7}, headers=owner)
    assert r.status_code == 200, r.text
    assert r.json()["minFreeGb"] == 10 and r.json()["low"] is True and r.json()["path"].endswith("/rec")
    async with session() as s:
        ms = [await media.save(s, None, "photo", b"x" * 10, "test", label=f"m{i}") for i in range(4)]
        ms[0].created_at = now() - timedelta(days=9)
        for i, m in enumerate(ms[1:], 1):
            m.created_at = now() - timedelta(minutes=10 - i)
        await commit(s)
        files = [media.file_of(m) for m in ms]
        assert all(f.is_file() and f.is_relative_to(tmp_path / "rec") for f in files)
        orig = media._drop_oldest

        async def drop(s: object, n: int) -> int:
            k = await orig(s, 1)
            free["v"] += 3 * media.GB
            return k

        monkeypatch.setattr(media, "_drop_oldest", drop)
        res = await media.rotate(s)
        await commit(s)
        assert res == {"low": False, "free": 11 * media.GB, "deleted": 3}
        left = (await s.scalars(select(Media))).all()
        assert [m.meta for m in left] == [{}] and not files[0].exists() and files[3].exists()
        free["v"] = 1 * media.GB
        assert (await media.rotate(s))["low"] is True
        await commit(s)
        assert (await s.scalars(select(Media))).all() == []
        assert await media.low(s)
    notes = (await client.get("/api/v1/notifications", headers=owner)).json()
    assert any(n["type"] == "media_low_space" for n in notes)
    assert (await client.patch("/api/v1/media/storage", json={"dir": "../../x"}, headers=owner)).status_code == 422


async def test_media_file_is_served_in_ranges(
    client: httpx.AsyncClient, owner: dict, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MEDIA_DIR", str(tmp_path))
    async with session() as s:
        m = await media.save(s, None, "video", bytes(range(100)), "test")
        await commit(s)
        mid = str(m.id)
    url = f"/api/v1/media/{mid}/file"
    r = await client.get(url, headers=owner)
    assert r.status_code == 200 and r.content == bytes(range(100)) and r.headers["content-type"] == "video/mp4"
    r = await client.get(url, headers={**owner, "Range": "bytes=10-19"})
    assert r.status_code == 206 and r.content == bytes(range(10, 20))
    assert r.headers["content-range"] == "bytes 10-19/100"
    r = await client.get(url, headers={**owner, "Range": "bytes=-5"})
    assert r.status_code == 206 and r.content == bytes(range(95, 100))
    assert (await client.get(url, headers={**owner, "Range": "bytes=200-"})).status_code == 416
    listed = (await client.get("/api/v1/media?kind=video", headers=owner)).json()
    assert [x["id"] for x in listed] == [mid]
    assert (await client.delete(url.removesuffix("/file"), headers=owner)).status_code == 204
    assert not any(tmp_path.rglob("*.mp4"))


def test_camera_trigger_matches_label_and_phase() -> None:
    b = blocks.BLOCKS["camera_event"]
    node = {"params": {"camera": "cam-yard", "label": "person", "phase": "start"}}
    ev = {"type": "camera", "device": "cam-yard", "camera": "yard", "label": "person", "phase": "once"}
    assert flows.match(node, b, ev, {}) == {"v": "person", "d": "cam-yard", "label": "person", "camera": "yard"}
    assert flows.match(node, b, {**ev, "label": "motion"}, {}) is None
    assert flows.match(node, b, {**ev, "phase": "end"}, {}) is None
    assert flows.match({"params": {"camera": "cam-yard", "phase": "end"}}, b, {**ev, "phase": "end"}, {})
    assert flows.match(node, b, {**ev, "device": "cam-door"}, {}) is None
    assert {"snapshot", "clip"} <= set(blocks.EXEC)


def test_driver_helpers_parse_onvif_and_sse() -> None:
    assert vc.with_auth("rtsp://old:x@10.0.0.1:554/s?a=1", "u@1", "p:w") == "rtsp://u%401:p%3Aw@10.0.0.1:554/s?a=1"
    with pytest.raises(vc.CameraError):
        vc.with_auth("nope", "u", "p")
    xml = (
        '<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" xmlns:wsnt="http://docs.oasis-open.org/wsn/b-2"'
        ' xmlns:tt="http://www.onvif.org/ver10/schema"><s:Body><PullMessagesResponse>'
        "<wsnt:NotificationMessage><wsnt:Topic>tns1:VideoSource/MotionAlarm</wsnt:Topic><wsnt:Message><tt:Message>"
        '<tt:Source><tt:SimpleItem Name="Source" Value="VS"/></tt:Source>'
        '<tt:Data><tt:SimpleItem Name="State" Value="true"/>'
        "</tt:Data></tt:Message></wsnt:Message></wsnt:NotificationMessage>"
        "<wsnt:NotificationMessage><wsnt:Topic>tns1:Device/Trigger/Relay</wsnt:Topic><wsnt:Message><tt:Message><tt:Data>"
        '<tt:SimpleItem Name="LogicalState" Value="inactive"/></tt:Data></tt:Message></wsnt:Message>'
        "</wsnt:NotificationMessage>"
        "</PullMessagesResponse></s:Body></s:Envelope>"
    )
    msgs = vc.onvif_messages(xml)
    assert msgs[0] == ("tns1:VideoSource/MotionAlarm", {"State": "true"})
    assert vc.onvif_motion(msgs) is True and vc.onvif_motion(msgs[1:]) is None
    assert vc.onvif_motion([("tns1:RuleEngine/CellMotionDetector/Motion", {"IsMotion": "false"})]) is False
    sse = tl.Sse()
    got = [sse.feed(x) for x in ["event: motion.started\n", 'data: {"active": true}\n', "\n", ": keepalive\n"]]
    assert got == [None, None, ("motion.started", {"active": True}), None]
    assert tl.motion_of("motion.stopped", {}) is False and tl.motion_of("state.changed", {}) is None
    assert tl.sse_error('{"status":"error","error":{"code":"http_404"}}') and not tl.sse_error("data: x")
    cfg = {"host": "http://192.168.0.105/", "user": "thingino", "password": "a/b", "token": "k"}
    assert tl.rtsp_url(cfg, "ch1") == "rtsp://thingino:a%2Fb@192.168.0.105/ch1"
    assert tl.stills(cfg)["preview"] == "http://192.168.0.105/x/ch1.jpg?token=k"
    with pytest.raises(tl.CameraError):
        tl.host_of({"host": "bad host;rm"})
    assert os.path.basename(str(SDK)) == "extensions"


async def test_lost_extension_marks_its_cameras_offline(client: httpx.AsyncClient, owner: dict, driver: list) -> None:
    from app.mqtt import main as mq

    await client.post(
        "/api/v1/cameras", json={"driver": DRIVER, "name": "Porch", "config": {"host": "h"}}, headers=owner
    )
    await mq.ext_message(DRIVER, "status", None, {"state": "stopping"})
    async with session() as s:
        assert (await s.get(Device, "cam-porch")).available is True
    await mq.ext_message(DRIVER, "status", None, {"state": "offline"})
    async with session() as s:
        assert (await s.get(Device, "cam-porch")).available is False


def test_record_settings_are_normalized() -> None:
    r = cameras.norm_record(
        {
            "mode": "continuous",
            "labels": ["Person", "motion", "person"],
            "schedule": {"mode": "hours", "from": "22:00", "to": "06:30"},
            "keep_days": 999,
            "detect": {"enabled": 1, "labels": ["person", "ufo"], "score": 0.01},
            "zones": [{"name": "Gate", "kind": "exclude", "points": [[0, 0], [1.5, 0], [0.5, 0.5]]}],
            "audio": 0,
        }
    )
    assert r["mode"] == "continuous" and r["labels"] == ["motion", "person"] and r["keep_days"] == 365
    assert r["detect"] == {"enabled": True, "labels": ["person"], "score": 0.2} and r["audio"] is False
    assert r["zones"][0]["kind"] == "exclude" and r["zones"][0]["points"][1] == [1.0, 0.0]
    for bad in ({"zones": [{"points": [[0, 0], [1, 1]]}]}, {"schedule": {"from": "25:00"}}, {"labels": "x"}):
        with pytest.raises(ApplicationError):
            cameras.norm_record(bad)
    night = cameras.norm_record({"schedule": {"mode": "hours", "from": "22:00", "to": "06:00"}})
    at = now().replace(hour=23, minute=0)
    assert cameras.scheduled(night, at) and not cameras.scheduled(night, at.replace(hour=12))
    assert cameras.scheduled(night, at.replace(hour=5, minute=59)) and cameras.scheduled(r, at.replace(hour=23))
    assert cameras.wants_label({"labels": ["person"]}, "person") and not cameras.wants_label(
        {"labels": ["person"]}, "motion"
    )
    assert cameras.wants_label({"labels": []}, "motion") and cameras.wants_label({"labels": ["car"]}, "clip")


async def test_camera_settings_actions_presets_and_status(
    client: httpx.AsyncClient, owner: dict, driver: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    pos = {"x": 100, "y": 50}
    found = {"same": False}

    async def fake_rpc(s: object, ext_id: str, method: str, params: dict, timeout: float = 10) -> dict:
        driver.append({"method": method, **params})
        if method == "camera.probe":
            h = params["config"]["host"]
            return {"streams": {"main": f"rtsp://{h}/ch0"}, "info": {"model": "PT", "mac": "aa", "ptz": True}}
        if method == "camera.settings":
            if params["op"] == "set":
                return {"fields": [], "failed": {"privacy": "nope"} if "privacy" in params["values"] else {}}
            return {
                "fields": [
                    {"key": "motion_enabled", "type": "bool", "section": "motion", "value": True},
                    {"key": "brightness", "type": "int", "section": "Image!", "value": 128, "min": 0, "max": 255},
                    {"key": "evil", "type": "script", "value": "x"},
                    {"key": "fw", "type": "info", "value": {"nested": 1}, "readonly": True},
                ]
            }
        if method == "camera.actions":
            return {"ok": True, "detail": params["action"]}
        if method == "camera.ptz":
            if params["op"] == "goto":
                pos.update(params["position"])
            return {"position": dict(pos)}
        if method == "camera.diagnose":
            return {"checks": [{"key": "network", "ok": True, "value": "h"}, {"no": "key"}]}
        if method == "camera.discover":
            return {"found": [{"host": "10.0.0.9", "mac": "aa", "same": found["same"]}, {"host": "10.0.0.7"}]}
        return {"ok": True}

    monkeypatch.setattr(cameras.extensions, "rpc", fake_rpc)
    r = await client.post(
        "/api/v1/cameras", json={"driver": DRIVER, "name": "Pt", "config": {"host": "10.0.0.5"}}, headers=owner
    )
    assert r.status_code == 201, r.text
    cam = r.json()
    assert cam["features"] == list(cameras.FEATURES) and cam["ptz"] is True and cam["status"]["code"] == "ok"
    r = await client.get("/api/v1/cameras/pt/settings", headers=owner)
    fields = r.json()["fields"]
    assert [f["key"] for f in fields] == ["motion_enabled", "brightness", "fw"]
    assert fields[1]["section"] == "image" and fields[2]["value"] == "{'nested': 1}" and fields[2]["readonly"]
    r = await client.patch("/api/v1/cameras/pt/settings", json={"values": {"privacy": True, "x": [1]}}, headers=owner)
    assert r.json()["failed"] == {"privacy": "nope"}
    assert driver[-1]["values"] == {"privacy": True, "x": "[1]"}
    guest = await guest_headers(client, owner)
    assert (
        await client.patch("/api/v1/cameras/pt/settings", json={"values": {"a": 1}}, headers=guest)
    ).status_code == 403
    r = await client.post("/api/v1/cameras/pt/action", json={"action": "sync_time"}, headers=owner)
    assert r.json() == {"ok": True, "detail": "sync_time"} and driver[-1]["params"]["timezone"]
    assert (await client.post("/api/v1/cameras/pt/action", json={"action": "format"}, headers=owner)).status_code == 422
    r = await client.post("/api/v1/cameras/pt/action", json={"action": "reboot"}, headers=owner)
    assert (
        r.status_code == 200
        and (await client.get("/api/v1/cameras/pt", headers=owner)).json()["status"]["code"] == "starting"
    )
    r = await client.post("/api/v1/cameras/pt/presets", json={"name": "Ворота"}, headers=owner)
    assert r.status_code == 201 and r.json()[0]["position"] == {"x": 100, "y": 50}
    pid = r.json()[0]["id"]
    pos.update(x=0, y=0)
    r = await client.post(f"/api/v1/cameras/pt/presets/{pid}/go", headers=owner)
    assert r.json()["position"] == {"x": 100, "y": 50}
    r = await client.patch(f"/api/v1/cameras/pt/presets/{pid}", json={"name": "Gate"}, headers=owner)
    assert r.json()[0]["name"] == "Gate"
    assert (await client.post("/api/v1/cameras/pt/presets/nope/go", headers=owner)).status_code == 404
    assert (await client.post("/api/v1/cameras/pt/ptz", json={"op": "drill"}, headers=owner)).status_code == 422
    r = await client.post("/api/v1/cameras/pt/ptz", json={"op": "move", "pan": 9, "tilt": -0.5}, headers=owner)
    assert r.status_code == 200 and driver[-1]["pan"] == 1.0 and driver[-1]["tilt"] == -0.5
    assert (await client.delete(f"/api/v1/cameras/pt/presets/{pid}", headers=owner)).json() == []
    r = await client.get("/api/v1/cameras/pt/diagnose", headers=owner)
    keys = [c["key"] for c in r.json()["checks"]]
    assert keys[:2] == ["driver", "network"] and "storage" in keys and "buffer" in keys
    r = await client.post("/api/v1/cameras/pt/discover", headers=owner)
    assert r.json()["match"] is None and len(r.json()["found"]) == 2
    found["same"] = True
    r = await client.post("/api/v1/cameras/pt/discover", headers=owner)
    assert r.json()["moved"] is True and r.json()["match"] == "10.0.0.9"
    async with session() as s:
        c = await s.get(Camera, "pt")
        assert c.config["host"] == "10.0.0.9" and "10.0.0.9" in str(
            cameras.secretbox.open_(c.streams["streams"]["main"])
        )
        await extensions.core_call(
            s, DRIVER, "cameras.health", {"camera": "pt", "reason": "other_device", "detail": "x"}
        )
        with pytest.raises(ApplicationError):
            await extensions.core_call(s, DRIVER, "cameras.health", {"camera": "pt", "reason": "bogus"})
        res = await extensions.core_call(s, DRIVER, "cameras.moved", {"camera": "pt", "host": "10.0.0.11"})
        assert res == {"ok": True, "changed": True}
        with pytest.raises(ApplicationError):
            await extensions.core_call(s, DRIVER, "cameras.moved", {"camera": "pt", "host": "bad host;"})
        await commit(s)
    cam = (await client.get("/api/v1/cameras/pt", headers=owner)).json()
    assert cam["status"]["code"] == "starting" and cam["config"]["host"] == "10.0.0.11"
    async with session() as s:
        await extensions.core_call(s, DRIVER, "cameras.health", {"camera": "pt", "reason": "auth_api"})
        await commit(s)
    assert (await client.get("/api/v1/cameras/pt", headers=owner)).json()["status"]["code"] == "auth_api"


async def test_offline_camera_notifies_and_returns(client: httpx.AsyncClient, owner: dict, driver: list) -> None:
    await client.post(
        "/api/v1/cameras", json={"driver": DRIVER, "name": "Back", "config": {"host": "h"}}, headers=owner
    )
    await client.patch("/api/v1/cameras/back", json={"record": {"offline_min": 5}}, headers=owner)
    async with session() as s:
        d = await s.get(Device, "cam-back")
        d.available = False
        await cameras.watch_offline(s)
        c = await s.get(Camera, "back")
        assert "down_since" in c.health and not c.health.get("notified")
        c.health = {**c.health, "down_since": (now() - timedelta(minutes=6)).isoformat()}
        await cameras.watch_offline(s)
        await commit(s)
    notes = (await client.get("/api/v1/notifications", headers=owner)).json()
    assert any(n["type"] == "camera_offline" and n["params"]["name"] == "Back" for n in notes)
    async with session() as s:
        (await s.get(Device, "cam-back")).available = True
        await cameras.watch_offline(s)
        await commit(s)
        assert (await s.get(Camera, "back")).health == {}
    notes = (await client.get("/api/v1/notifications", headers=owner)).json()
    assert not any(n["type"] in ("camera_offline", "camera_online") for n in notes)
    log = (await client.get("/api/v1/events?limit=20", headers=owner)).json()
    items = log["items"] if isinstance(log, dict) else log
    assert any(e["type"] == "camera.online" for e in items)


async def test_media_keep_bulk_delete_days_and_zip(
    client: httpx.AsyncClient, owner: dict, driver: list, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import io
    import zipfile

    monkeypatch.setenv("MEDIA_DIR", str(tmp_path))
    await client.post(
        "/api/v1/cameras", json={"driver": DRIVER, "name": "Side", "config": {"host": "h"}}, headers=owner
    )
    async with session() as s:
        e = CameraEvent(camera_id="side", label="motion", source="driver", started_at=now(), ended_at=now())
        s.add(e)
        await s.flush()
        ms = [await media.save(s, "side", "photo", b"\xff\xd8" + bytes([i]) * 10, "test") for i in range(3)]
        await cameras.attach(s, e.id, snapshot_id=ms[0].id)
        await commit(s)
        ids = [str(m.id) for m in ms]
        eid = e.id
    r = await client.patch(f"/api/v1/media/{ids[1]}", json={"keep": True}, headers=owner)
    assert r.json()["keep"] is True
    days = (await client.get("/api/v1/media/days?camera=side", headers=owner)).json()
    assert len(days) == 1 and days[0]["photos"] == 3
    r = await client.get(f"/api/v1/media/zip?ids={ids[1]},{ids[2]}", headers=owner)
    assert r.status_code == 200 and len(zipfile.ZipFile(io.BytesIO(r.content)).namelist()) == 2
    assert not list((tmp_path / ".valo-tmp").glob("*.zip"))
    guest = await guest_headers(client, owner)
    assert (await client.post("/api/v1/media/delete", json={"ids": ids}, headers=guest)).status_code == 403
    r = await client.delete(f"/api/v1/cameras/side/events/{eid}", headers=owner)
    assert r.json() == {"deleted": 1}
    r = await client.post("/api/v1/media/delete", json={"camera": "side", "all": True}, headers=owner)
    assert r.json()["deleted"] == 1 and r.json()["skipped"] == 1
    async with session() as s:
        assert [str(m.id) for m in (await s.scalars(select(Media))).all()] == [ids[1]]
        m = await s.get(Media, ms[1].id)
        m.created_at = now() - timedelta(days=90)
        await commit(s)
        await media.rotate(s)
        await commit(s)
        assert await s.get(Media, ms[1].id) is not None
    r = await client.delete("/api/v1/cameras/side?media=delete", headers=owner)
    assert r.status_code == 204 and not any(tmp_path.rglob("*.jpg"))
    assert (await client.post("/api/v1/media/delete", json={}, headers=owner)).status_code == 422


def test_ntp_reply_and_thingino_settings() -> None:
    from app.cameras import main as cm

    req = bytes([0x23]) + bytes(39) + b"ORIGINTS"
    out = cm.ntp_reply(req, 1000.5, 1000.5)
    assert out is not None and len(out) == 48 and out[0] & 7 == 4 and out[1] == 3 and out[24:32] == b"ORIGINTS"
    assert cm.ntp_reply(bytes([0x24]) + bytes(47), 1, 1) is None and cm.ntp_reply(b"x", 1, 1) is None
    assert cm.piece_start("rec-20261107-101000.mp4", "Europe/Kyiv").hour == 10
    assert cm.tracks(False)[-1] == "-an" and "0:a:0?" in cm.tracks(True)
    doc = {
        "motion": {"enabled": True},
        "daynight": {"enabled": False, "force_mode": "night"},
        "privacy": {"enabled": False},
        "image": {"brightness": 128, "anti_flicker": 1, "hflip": False},
        "streams": [{"width": 1920, "height": 1080, "fps": 25, "bitrate": 4000, "format": "H264"}],
        "backend": {"raw": {"motion": {"sensitivity": 3, "cooldown_time": 5}}},
    }
    schema = {"settings": {"motion": {"enabled": {}, "sensitivity": {}}, "image": {"brightness": {}}}}
    hb = {"time_now": 1010, "mic_enabled": 1, "ir940_state": 0}
    f = {x["key"]: x for x in tl.fields_of(doc, hb, schema, {"tz_name": "Europe/Kyiv"}, 1000)}
    assert f["daynight_mode"]["value"] == "night" and f["daynight_mode"]["readonly"]
    assert f["motion_sensitivity"]["value"] == 3 and "readonly" not in f["motion_sensitivity"]
    assert f["anti_flicker"]["value"] == "50" and f["clock_drift"]["value"] == 10 and f["ir_light"]["value"] == "off"
    assert f["main_size"]["value"] == "1920x1080 H264" and f["mic_enabled"]["readonly"] and "sub_fps" not in f
    assert tl.patch_of("daynight_mode", "day", {})[1][2] == {"force_mode": "day"}
    assert tl.patch_of("anti_flicker", "60", {})[0][2] == {"anti_flicker": 2}
    assert tl.patch_of("main_fps", 15, {})[0][1] == "/api/v1/settings/streams/0/fps"
    for k, v in (("motion_sensitivity", 9), ("brightness", "x"), ("mic_enabled", True), ("ssh", 1), ("privacy", "yes")):
        with pytest.raises(tl.CameraError):
            tl.patch_of(k, v, {})
    assert len(tl.subnet_hosts("192.168.0.100:80")) == 254 and tl.subnet_hosts("cam.local") == []
    assert tl.is_thingino(b"<html><title>thingino</title>") and not tl.is_thingino(b"<title>TP-Link</title>")
    assert tl.same_camera({"id": "02:00:5E:10:AA:01"}, "02005e10aa01") and not tl.same_camera({}, "")
    assert tl.motor_status({"message": {"xpos": "10", "ypos": 5}}) == {"x": 10, "y": 5}
    assert tl.motor_status({"message": "ok"}) is None and tl.jog_steps(0.5, -1, 4000, 2000) == (500, -500)
    assert tl.streamer_running({"checks": {"streaming": {"running": False}}}) is False
    assert tl.streamer_running({"checks": {"system": {"streamer_running": True}}}) is True
    assert tl.streamer_running({}) is None and tl.motor_busy({"message": {"status": "1"}})
    assert tl.motor_limits({"message": {"xmax": "3900", "ymax": "2200"}}) == (3900, 2200)
    assert tl.tz_posix("../etc/passwd") == "" and tl.tz_posix("No/Such") == ""
    if os.path.exists("/usr/share/zoneinfo/Europe/Kyiv"):
        assert tl.tz_posix("Europe/Kyiv").startswith("EET-2EEST")


async def test_moved_camera_reaches_the_driver_with_new_host(
    client: httpx.AsyncClient, owner: dict, driver: list
) -> None:
    body = {"driver": DRIVER, "name": "Pt", "config": {"host": "10.0.0.7", "password": "p"}}
    assert (await client.post("/api/v1/cameras", json=body, headers=owner)).status_code == 201
    driver.clear()
    async with session() as s:
        res = await extensions.core_call(s, DRIVER, "cameras.moved", {"camera": "pt", "host": "10.0.0.1"})
        await commit(s)
    assert res["changed"] is True
    await cameras.reprobe("pt")
    syncs = [c for c in driver if c["method"] == "camera.sync"]
    assert syncs and syncs[-1]["cameras"][0]["config"]["host"] == "10.0.0.1"
    driver.clear()
    async with session() as s:
        res = await extensions.core_call(s, DRIVER, "cameras.moved", {"camera": "pt", "host": "10.0.0.1"})
        await commit(s)
    assert res["changed"] is False
    assert [c["method"] for c in driver] == ["camera.sync"]
