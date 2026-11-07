from types import SimpleNamespace

import httpx
import pytest

from app.domain import mqttx
from app.lib import settings as settings_mod
from app.lib.kv import kv
from app.server import base

pytestmark = pytest.mark.anyio


def conn(peer: str, xff: str = "") -> SimpleNamespace:
    return SimpleNamespace(client=SimpleNamespace(host=peer), headers={"x-forwarded-for": xff} if xff else {})


def test_client_ip_behind_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings_mod, "settings", settings_mod.Settings(trusted_proxies="172.16.0.0/12,127.0.0.1/32"))
    monkeypatch.setattr(base, "settings", settings_mod.settings)
    base._trusted.cache_clear()
    assert base.client_ip(conn("172.20.0.5", "192.168.1.20")) == "192.168.1.20"
    assert base.client_ip(conn("172.20.0.5", "1.2.3.4, 192.168.1.20, 172.20.0.9")) == "192.168.1.20"
    assert base.client_ip(conn("203.0.113.7", "10.0.0.1")) == "203.0.113.7"
    assert base.client_ip(conn("172.20.0.5")) == "172.20.0.5"
    assert base.client_ip(conn("172.20.0.5", "172.20.0.9")) == "172.20.0.9"
    base._trusted.cache_clear()


def test_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        settings_mod,
        "settings",
        settings_mod.Settings(valo_env="real", demo=False, peers="demo=http://localhost:3000, bad, x="),
    )
    assert settings_mod.environment() == {
        "name": "real",
        "demo": False,
        "peers": [{"name": "demo", "url": "http://localhost:3000"}],
    }


async def test_setup_status_reports_env(client: httpx.AsyncClient) -> None:
    r = await client.get("/api/v1/setup")
    body = r.json()
    assert r.status_code == 200 and body["done"] is False
    assert set(body["env"]) == {"name", "demo", "peers"}


async def test_login_rate_limit(client: httpx.AsyncClient, owner: dict) -> None:
    codes = [
        (await client.post("/api/v1/auth/login", json={"username": "mikko", "password": "nope"})).status_code
        for _ in range(11)
    ]
    assert codes[:10] == [401] * 10 and codes[10] == 429


async def test_dynsec_role_recreated_on_acl_change(client: httpx.AsyncClient, monkeypatch) -> None:
    calls: list[list[str]] = []

    async def fake(*commands, timeout: float = 5.0):
        calls.append([c["command"] for c in commands])
        return [{"command": c["command"]} for c in commands]

    monkeypatch.setattr(mqttx, "dynsec", fake)
    acl = mqttx.full_acl("zigbee2mqtt/#")
    await mqttx.ensure("zigbee2mqtt", "pw", "svc-zigbee2mqtt", acl, reset=False)
    await mqttx.ensure("zigbee2mqtt", "pw", "svc-zigbee2mqtt", acl, reset=False)
    assert len(calls) == 1
    assert calls[0] == ["deleteRole", "createRole", "createClient", "addClientRole", "setClientPassword"]
    await mqttx.ensure(
        "zigbee2mqtt", "pw", "svc-zigbee2mqtt", mqttx.full_acl("zigbee2mqtt/#", "homeassistant/#"), reset=False
    )
    assert len(calls) == 2
    await mqttx.ensure("dev-x", "pw", "dev-x", acl)
    assert calls[2][0] == "deleteClient"
    assert await kv().get("mqtt:acct:zigbee2mqtt")


async def test_backup_prune_keeps_latest(client: httpx.AsyncClient, tmp_path, monkeypatch) -> None:
    from datetime import timedelta

    from sqlalchemy import select

    from app.db.base import commit, now, session
    from app.db.models import Backup
    from app.domain import system

    monkeypatch.setattr(system, "BACKUP_KEEP", 3)
    files = []
    async with session() as s:
        for i in range(5):
            f = tmp_path / f"b{i}.tar.gz"
            f.write_bytes(b"x")
            files.append(f)
            s.add(Backup(kind="manual", status="ok", path=str(f), size=1, created_at=now() - timedelta(hours=i)))
        s.add(Backup(kind="manual", status="failed", path="", created_at=now() - timedelta(days=9)))
        await commit(s)
    async with session() as s:
        await system._prune(s)
        await commit(s)
    assert [f.exists() for f in files] == [True, True, True, False, False]
    async with session() as s:
        rows = (await s.scalars(select(Backup))).all()
        assert sorted(b.status for b in rows) == ["failed", "ok", "ok", "ok"]


async def test_backup_mirror_copy_prune_and_fallback(
    client: httpx.AsyncClient, owner: dict, tmp_path, monkeypatch
) -> None:
    from app.db.base import commit, session
    from app.db.models import Backup
    from app.domain import system

    mirror = tmp_path / "mirror"
    monkeypatch.setattr(system, "BACKUP_MIRROR", mirror)
    src = tmp_path / "valo-1.tar.gz"
    src.write_bytes(b"archive")
    system._mirror(src)
    assert (mirror / src.name).read_bytes() == b"archive"
    assert not list(mirror.glob(".*.part"))
    async with session() as s:
        b = Backup(kind="manual", status="ok", path=str(src), size=7)
        s.add(b)
        await s.flush()
        bid = str(b.id)
        await commit(s)
    src.unlink()
    async with session() as s:
        p = (await client.get("/api/v1/auth/me", headers=owner)).json()
        from app.domain.common import Principal

        principal = Principal(id=p["id"], username=p["username"], name=p["name"], role="owner")
        assert await system.backup_file(s, principal, bid) == mirror / src.name
    system._unlink(str(src))
    assert not (mirror / src.name).exists()


async def test_running_backup_after_restore_is_settled(client: httpx.AsyncClient, owner: dict, tmp_path) -> None:
    from datetime import timedelta

    from sqlalchemy import select

    from app.db.base import commit, now, session
    from app.db.models import Backup
    from app.domain import system

    async with session() as s:
        snap = Backup(kind="manual", status="running", created_at=now())
        other = Backup(kind="scheduled", status="running", created_at=now())
        s.add_all([snap, other])
        await s.flush()
        sid, oid = snap.id, other.id
        await commit(s)
    assert (await client.post("/api/v1/system/backups", json={}, headers=owner)).status_code == 409
    archive = tmp_path / "valo-x.tar.gz"
    archive.write_bytes(b"x" * 10)
    async with session() as s:
        await system.restored(s, str(archive), {"id": str(sid)})
        await commit(s)
    async with session() as s:
        rows = {b.id: b for b in (await s.scalars(select(Backup))).all()}
        assert rows[sid].status == "ok" and rows[sid].path == str(archive) and rows[sid].size == 10
        assert rows[oid].status == "failed" and rows[oid].note == "interrupted"
        s.add(Backup(kind="manual", status="running", created_at=now() - timedelta(hours=2)))
        await commit(s)
    r = await client.post("/api/v1/system/backups", json={}, headers=owner)
    assert r.status_code == 202, r.text


async def test_error_log_collects_groups_and_reports(client: httpx.AsyncClient, owner: dict) -> None:
    import logging

    from app.lib import errlog, log

    handler = errlog.Handler("mqtt")
    logger = logging.getLogger("valo.test.errors")
    logger.addHandler(handler)
    logger.propagate = False
    try:
        for _ in range(3):
            logger.error({"event": "message_failed", "topic": "zigbee2mqtt/x", "logger": "mqtt_proc"})
        try:
            raise ValueError("boom")
        except ValueError:
            logger.exception("parse failed")
        logger.warning({"event": "not stored"})
    finally:
        logger.removeHandler(handler)
    body = (await client.get("/api/v1/system/errors", headers=owner)).json()
    by = {x["event"]: x for x in body["items"]}
    assert set(by) == {"message_failed", "parse failed"}
    assert by["message_failed"]["count"] == 3 and by["message_failed"]["process"] == "mqtt"
    assert "zigbee2mqtt/x" in by["message_failed"]["detail"]
    assert "ValueError: boom" in by["parse failed"]["trace"]
    assert body["unseen"] == 2
    info = (await client.get("/api/v1/system", headers=owner)).json()
    assert info["errors"] == 2
    r = await client.post(
        "/api/v1/system/errors/report",
        json={
            "source": "browser",
            "message": "TypeError: x is undefined",
            "stack": "at f (app.js:1)",
            "url": "/en/x?a=1",
        },
        headers=owner,
    )
    assert r.status_code == 204
    bad = await client.post("/api/v1/system/errors/report", json={"source": "kernel", "message": "x"}, headers=owner)
    assert bad.status_code == 422
    assert (await client.post("/api/v1/system/errors/seen", json={}, headers=owner)).status_code == 204
    body = (await client.get("/api/v1/system/errors", headers=owner)).json()
    assert body["unseen"] == 0 and any(x["process"] == "browser" for x in body["items"])
    assert (await client.delete("/api/v1/system/errors", headers=owner)).status_code == 204
    assert (await client.get("/api/v1/system/errors", headers=owner)).json()["items"] == []
    assert log.get("x") is not None


def test_error_log_trims_to_limit(monkeypatch) -> None:
    from redis import Redis

    from app.lib import errlog
    from app.lib.settings import settings

    r = Redis.from_url(settings.redis_url, decode_responses=True)
    r.delete(errlog.ITEMS, errlog.INDEX)
    monkeypatch.setattr(errlog, "LIMIT", 5)
    for i in range(8):
        errlog.store(r, errlog.entry("worker", "tasks", f"e{i}", "error", "", "", 1000.0 + i))
    assert r.zcard(errlog.INDEX) == 5 and r.hlen(errlog.ITEMS) == 5
    assert set(r.zrange(errlog.INDEX, 0, -1)) == {errlog.fingerprint("worker", "tasks", f"e{i}") for i in range(3, 8)}
    r.delete(errlog.ITEMS, errlog.INDEX)
    r.close()


async def test_backup_tasks_run_once_and_exclusive(client: httpx.AsyncClient, owner: dict, monkeypatch) -> None:
    from app.domain import system
    from app.domain import tasks as T

    calls: list[str] = []

    async def fake_restore(path: str) -> dict:
        calls.append(path)
        return {}

    monkeypatch.setattr(system, "restore_run", fake_restore)
    token = await system._once_token()
    await T.backups_restore("/data/backups/a.tar.gz", "user:mikko", token)
    await T.backups_restore("/data/backups/a.tar.gz", "user:mikko", token)
    assert calls == ["/data/backups/a.tar.gz"]
    assert await system.acquire("someone")
    token2 = await system._once_token()
    await T.backups_restore("/data/backups/b.tar.gz", "user:mikko", token2)
    assert calls == ["/data/backups/a.tar.gz"]
    evs = (await client.get("/api/v1/events?kind=backup", headers=owner)).json()
    assert any(e["type"] == "backup.restore_failed" for e in evs)
    await system.release("someone")
    assert await system.acquire("other") and not await system.acquire("third")
    await system.release("other")


async def test_backup_upload_validates_archive(client: httpx.AsyncClient, owner: dict, tmp_path, monkeypatch) -> None:
    import io
    import json as js
    import tarfile

    from app.domain import system

    monkeypatch.setattr(system, "BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(system, "BACKUP_MIRROR", tmp_path / "mirror")

    def archive(files: dict[str, bytes]) -> bytes:
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            for name, data in files.items():
                info = tarfile.TarInfo(name)
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
        return buf.getvalue()

    good = archive({"db.dump": b"PGDMP", "meta.json": js.dumps({"created": "2026-11-05T10:00:00"}).encode()})
    hdr = {**owner, "content-type": "application/octet-stream", "x-filename": "home.tar.gz"}
    r = await client.post("/api/v1/system/backups/upload", content=good, headers=hdr)
    assert r.status_code == 201, r.text
    b = r.json()
    assert b["kind"] == "uploaded" and b["status"] == "ok" and b["size"] == len(good)
    saved = list((tmp_path / "backups").glob("*-uploaded.tar.gz"))
    assert len(saved) == 1 and (tmp_path / "mirror" / saved[0].name).exists()
    assert not list((tmp_path / "backups").glob("*.part"))
    bad = await client.post("/api/v1/system/backups/upload", content=b"not a tar", headers=hdr)
    assert bad.status_code == 422 and bad.json()["code"] == "backup_invalid"
    extra = archive({"db.dump": b"x", "../../etc/passwd": b"x"})
    assert (await client.post("/api/v1/system/backups/upload", content=extra, headers=hdr)).status_code == 422
    nodump = archive({"meta.json": b"{}"})
    assert (await client.post("/api/v1/system/backups/upload", content=nodump, headers=hdr)).status_code == 422
    assert len(list((tmp_path / "backups").iterdir())) == 1


async def test_backup_download_is_gzip_and_plain_tar_upload_works(
    client: httpx.AsyncClient, owner: dict, tmp_path, monkeypatch
) -> None:
    import io
    import tarfile

    from app.domain import system

    monkeypatch.setattr(system, "BACKUP_DIR", tmp_path / "b")
    monkeypatch.setattr(system, "BACKUP_MIRROR", None)
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        info = tarfile.TarInfo("db.dump")
        info.size = 5
        tar.addfile(info, io.BytesIO(b"PGDMP"))
    hdr = {**owner, "content-type": "application/octet-stream", "x-filename": "plain%20copy.tar"}
    r = await client.post("/api/v1/system/backups/upload", content=buf.getvalue(), headers=hdr)
    assert r.status_code == 201, r.text
    assert "plain copy.tar" in r.json()["note"]
    d = await client.get(f"/api/v1/system/backups/{r.json()['id']}/download", headers=owner)
    assert d.status_code == 200 and d.headers["content-type"].startswith("application/gzip")
    assert "content-encoding" not in d.headers


def test_browser_errors_from_foreign_scripts_are_ignored() -> None:
    from app.domain.system import foreign

    meta = "i: Failed to connect to MetaMask\n    at Object.connect (chrome-extension://nkbih/scripts/inpage.js:9:6184)"
    assert foreign("Failed to connect to MetaMask", meta)
    assert foreign("Script error.", "")
    own = "TypeError: x is undefined\n    at http://localhost:3000/_app/immutable/nodes/2.js:1:10"
    assert not foreign("x is undefined", own)
    mixed = own + "\n    at chrome-extension://abc/content.js:1:1"
    assert not foreign("x is undefined", mixed)


async def test_background_loop_survives_errors() -> None:
    import asyncio

    from app.lib import log
    from app.lib.loops import forever

    calls: list[int] = []
    done = asyncio.Event()

    async def flaky() -> None:
        calls.append(1)
        if len(calls) < 3:
            raise ConnectionError("redis: Temporary failure in name resolution")
        done.set()
        await asyncio.sleep(3600)

    task = asyncio.create_task(forever("test_loop", flaky, log.get("test"), pause=0.01))
    await asyncio.wait_for(done.wait(), 5)
    task.cancel()
    assert len(calls) == 3


def test_error_fingerprint_ignores_task_numbers_and_addresses() -> None:
    from app.lib import errlog

    a = errlog.fingerprint(
        "ws", "asyncio", "Task exception was never retrieved future: <Task name='Task-62' at 0x7f3a2b1c>"
    )
    b = errlog.fingerprint(
        "ws", "asyncio", "Task exception was never retrieved future: <Task name='Task-69' at 0x7f99aa00>"
    )
    assert a == b
    assert errlog.fingerprint("w", "t", "e3") != errlog.fingerprint("w", "t", "e4")


async def test_redis_socket_timeout_outlasts_blocking_waits(client: httpx.AsyncClient) -> None:
    from app.lib import kv as kvmod

    kwargs = kvmod.kv().connection_pool.connection_kwargs
    assert kwargs["socket_timeout"] == kvmod.SOCKET_TIMEOUT > kvmod.BLOCK_MAX
    assert await kvmod.kv().brpop(["test:empty-queue"], timeout=kvmod.BLOCK_MAX) is None
