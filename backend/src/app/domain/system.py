import asyncio
import base64
import json
import os
import pathlib
import platform
import shutil
import tarfile
import tempfile
import time
import urllib.request
import uuid
from datetime import datetime, timedelta
from importlib.metadata import version
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import DATABASE_URL, after, now
from app.db.models import Backup, Extension
from app.domain import events, zigbee
from app.domain.common import Principal, S, as_uuid, out
from app.lib import errlog, log, tasks
from app.lib.errors import ApplicationError
from app.lib.kv import alive, get_json, hit, kv
from app.lib.settings import env, env_int

BACKUP_DIR = pathlib.Path(env("BACKUP_DIR", "/data/backups"))
BACKUP_KEEP = env_int("BACKUP_KEEP", 7)
BACKUP_MIRROR = pathlib.Path(env("BACKUP_MIRROR")) if env("BACKUP_MIRROR") else None
BACKUP_OVERDUE = timedelta(hours=26)
UPDATE_URL = env("UPDATE_URL")
_log = log.get("system")


class BackupOut(S):
    id: uuid.UUID
    kind: str
    status: str
    size: int
    note: str | None
    created_at: datetime
    finished_at: datetime | None


def _pg_url() -> str:
    return DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")


LOCK = "backup:lock"
LOCK_TTL = 3600


async def once(token: str) -> bool:
    return bool(await kv().delete(f"backup:once:{token}"))


async def _once_token() -> str:
    token = uuid.uuid4().hex
    await kv().set(f"backup:once:{token}", "1", ex=86400)
    return token


async def acquire(owner: str) -> bool:
    return bool(await kv().set(LOCK, owner, nx=True, ex=LOCK_TTL))


async def release(owner: str) -> None:
    if await kv().get(LOCK) == owner:
        await kv().delete(LOCK)


async def _run(*cmd: str) -> None:
    env = {**os.environ, "PGOPTIONS": "-c lock_timeout=60s"}
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env
    )
    _, err = await proc.communicate()
    if proc.returncode:
        raise RuntimeError(f"{cmd[0]} exit {proc.returncode}: {err.decode(errors='replace')[-400:]}")


async def backups(s: AsyncSession) -> list[BackupOut]:
    return [
        out(b, BackupOut) for b in (await s.scalars(select(Backup).order_by(Backup.created_at.desc()).limit(50))).all()
    ]


async def backup_create(s: AsyncSession, p: Principal | None, kind: str = "manual") -> BackupOut:
    if p:
        p.need("admin")
    stale = now() - timedelta(hours=1)
    for r in (await s.scalars(select(Backup).where(Backup.status == "running"))).all():
        if r.created_at >= stale:
            raise ApplicationError("backup_busy", 409)
        r.status, r.finished_at, r.note = "failed", now(), "interrupted"
        _log.warning("backup_stale", backup=str(r.id))
    b = Backup(kind=kind, status="running", created_at=now())
    s.add(b)
    await s.flush()
    await events.add(s, "backup.started", actor=p.actor if p else "system", params={"kind": kind})
    bid, token = str(b.id), await _once_token()
    after(s, lambda: tasks.kick("backups.run", id=bid, token=token))
    return out(b, BackupOut)


async def backup_overdue(s: AsyncSession) -> bool:
    """Ежедневная копия включена, а копии по расписанию нет дольше BACKUP_OVERDUE, например узел был выключен ночью."""
    if not (await events.home(s)).settings.get("autoBackup", True):
        return False
    last = await s.scalar(select(func.max(Backup.created_at)).where(Backup.kind == "scheduled"))
    return last is None or now() - last > BACKUP_OVERDUE


async def backup_run(s: AsyncSession, backup_id: str) -> None:
    b = await s.get(Backup, as_uuid(backup_id))
    if b is None or b.status != "running":
        return
    await s.commit()
    notes = []
    try:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as tmp:
            t = pathlib.Path(tmp)
            await _run("pg_dump", "--format=custom", "--no-owner", f"--file={t / 'db.dump'}", _pg_url())
            try:
                z = await zigbee.backup()
                if z:
                    (t / "zigbee2mqtt.zip").write_bytes(base64.b64decode(z))
            except ApplicationError as e:
                notes.append(f"zigbee:{e.code}")
            exts = [
                {"id": x.id, "version": x.version, "enabled": x.enabled, "settings": x.settings, "grants": x.grants}
                for x in (await s.scalars(select(Extension))).all()
            ]
            (t / "meta.json").write_text(
                json.dumps(
                    {"id": backup_id, "created": now().isoformat(), "core": version("valo"), "extensions": exts},
                    ensure_ascii=False,
                    indent=1,
                )
            )
            path = BACKUP_DIR / f"valo-{now().strftime('%Y%m%d-%H%M%S')}-{b.kind}.tar.gz"
            await asyncio.to_thread(_pack, t, path)
        if BACKUP_MIRROR is not None:
            try:
                await asyncio.to_thread(_mirror, path)
            except OSError as e:
                _log.error("backup_mirror_failed", path=str(path), mirror=str(BACKUP_MIRROR), error=str(e))
                notes.append("mirror:failed")
        b.status, b.path, b.size, b.finished_at, b.note = (
            "ok",
            str(path),
            path.stat().st_size,
            now(),
            ", ".join(notes) or None,
        )
        await events.add(s, "backup.done", "ok", params={"kind": b.kind, "size": b.size, "notes": notes})
        await events.resolve(s, "backup:failed")
        await _prune(s)
    except Exception as e:
        _log.error("backup_failed", backup=backup_id, error=str(e), exc_info=True)
        b.status, b.finished_at, b.note = "failed", now(), str(e)[:500]
        await events.add(s, "backup.failed", "crit", params={"kind": b.kind, "error": str(e)[:300]})
        await events.notify(s, "backup:failed", "crit", "backup_failed", {}, "system")


def _mirror(path: pathlib.Path) -> None:
    assert BACKUP_MIRROR is not None
    BACKUP_MIRROR.mkdir(parents=True, exist_ok=True)
    tmp = BACKUP_MIRROR / f".{path.name}.part"
    shutil.copyfile(path, tmp)
    tmp.replace(BACKUP_MIRROR / path.name)


def _unlink(path: str) -> None:
    pathlib.Path(path).unlink(missing_ok=True)
    if BACKUP_MIRROR is not None and path:
        (BACKUP_MIRROR / pathlib.Path(path).name).unlink(missing_ok=True)


def _pack(src: pathlib.Path, dst: pathlib.Path) -> None:
    with tarfile.open(dst, "w:gz") as tar:
        for f in sorted(src.iterdir()):
            tar.add(f, arcname=f.name)


async def _prune(s: AsyncSession) -> None:
    rows = (await s.scalars(select(Backup).where(Backup.status == "ok").order_by(Backup.created_at.desc()))).all()
    for b in rows[BACKUP_KEEP:]:
        _unlink(b.path)
        await s.delete(b)


UPLOAD_LIMIT = 1024 * 1024 * 1024
_ALLOWED = {"db.dump", "meta.json", "zigbee2mqtt.zip"}


def _check_archive(path: pathlib.Path) -> dict[str, Any]:
    try:
        with tarfile.open(path, "r:*") as tar:
            names = {m.name for m in tar.getmembers() if m.isfile()}
            if "db.dump" not in names or not names <= _ALLOWED:
                raise ApplicationError("backup_invalid", 422)
            raw = tar.extractfile("meta.json") if "meta.json" in names else None
            return json.loads(raw.read()) if raw else {}
    except (tarfile.TarError, OSError, EOFError, ValueError) as e:
        raise ApplicationError("backup_invalid", 422) from e


async def backup_upload(s: AsyncSession, p: Principal, data: bytes, filename: str) -> BackupOut:
    p.need("owner")
    if not data:
        raise ApplicationError("backup_invalid", 422)
    if len(data) > UPLOAD_LIMIT:
        raise ApplicationError("backup_too_large", 413)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    path = BACKUP_DIR / f"valo-{now().strftime('%Y%m%d-%H%M%S')}-uploaded.tar.gz"
    tmp = path.with_suffix(".part")
    await asyncio.to_thread(tmp.write_bytes, data)
    try:
        meta = await asyncio.to_thread(_check_archive, tmp)
    except ApplicationError:
        tmp.unlink(missing_ok=True)
        _log.warning("backup_upload_invalid", file=filename[:120], size=len(data))
        raise
    tmp.replace(path)
    if BACKUP_MIRROR is not None:
        try:
            await asyncio.to_thread(_mirror, path)
        except OSError as e:
            _log.error("backup_mirror_failed", path=str(path), error=str(e))
    note = f"{filename[:120]}, {meta.get('created', '')[:19]}".strip(", ")
    b = Backup(
        kind="uploaded", status="ok", path=str(path), size=len(data), note=note, created_at=now(), finished_at=now()
    )
    s.add(b)
    await s.flush()
    await events.add(s, "backup.uploaded", "ok", actor=p.actor, params={"file": filename[:120], "size": len(data)})
    return out(b, BackupOut)


async def backup_skipped(s: AsyncSession, backup_id: str) -> None:
    b = await s.get(Backup, as_uuid(backup_id))
    if b is not None and b.status == "running":
        b.status, b.finished_at, b.note = "failed", now(), "busy"


async def backup_file(s: AsyncSession, p: Principal, backup_id: str) -> pathlib.Path:
    p.need("admin")
    b = await s.get(Backup, as_uuid(backup_id))
    if b is None or b.status != "ok" or not b.path:
        raise ApplicationError("backup_not_found", 404)
    for path in (pathlib.Path(b.path), BACKUP_MIRROR / pathlib.Path(b.path).name if BACKUP_MIRROR else None):
        if path is not None and path.is_file():
            return path
    raise ApplicationError("backup_not_found", 404)


async def backup_delete(s: AsyncSession, p: Principal, backup_id: str) -> None:
    p.need("admin")
    b = await s.get(Backup, as_uuid(backup_id))
    if b is None:
        raise ApplicationError("backup_not_found", 404)
    if b.path:
        _unlink(b.path)
    await s.delete(b)


async def restore(s: AsyncSession, p: Principal, backup_id: str) -> None:
    p.need("owner")
    path = await backup_file(s, p, backup_id)
    if await kv().get(LOCK):
        raise ApplicationError("backup_busy", 409)
    await events.add(s, "backup.restore_started", "warn", actor=p.actor, params={"file": path.name})
    token = await _once_token()
    after(s, lambda: tasks.kick("backups.restore", path=str(path), actor=p.actor, token=token))


async def restore_run(path: str) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        meta = await asyncio.to_thread(_unpack, pathlib.Path(path), pathlib.Path(tmp))
        await _run(
            "pg_restore",
            "--clean",
            "--if-exists",
            "--no-owner",
            "--single-transaction",
            f"--dbname={_pg_url()}",
            str(pathlib.Path(tmp) / "db.dump"),
        )
    return meta


async def restored(s: AsyncSession, path: str, meta: dict[str, Any]) -> None:
    f = pathlib.Path(path)
    for r in (await s.scalars(select(Backup).where(Backup.status == "running"))).all():
        if meta.get("id") and str(r.id) == meta["id"]:
            r.status, r.path, r.size, r.finished_at = "ok", str(f), f.stat().st_size if f.exists() else 0, now()
        else:
            r.status, r.finished_at, r.note = "failed", now(), "interrupted"


def _unpack(src: pathlib.Path, dst: pathlib.Path) -> dict[str, Any]:
    with tarfile.open(src, "r:*") as tar:
        tar.extract("db.dump", dst, filter="data")
        try:
            raw = tar.extractfile("meta.json")
        except KeyError:
            return {}
        return json.loads(raw.read()) if raw else {}


def _meminfo() -> dict[str, int]:
    try:
        rows = pathlib.Path("/proc/meminfo").read_text().splitlines()
        return {r.split(":")[0]: int(r.split()[1]) * 1024 for r in rows if len(r.split()) >= 2}
    except OSError:
        return {}


def _cpu() -> tuple[int, int]:
    try:
        vals = [int(x) for x in pathlib.Path("/proc/stat").read_text().splitlines()[0].split()[1:]]
        return sum(vals), vals[3] + (vals[4] if len(vals) > 4 else 0)
    except OSError:
        return 0, 0


async def resources(s: AsyncSession) -> dict[str, Any]:
    t1, i1 = _cpu()
    await asyncio.sleep(0.25)
    t2, i2 = _cpu()
    mem = _meminfo()
    disk = shutil.disk_usage(BACKUP_DIR if BACKUP_DIR.exists() else "/")
    db = await s.scalar(text("select pg_database_size(current_database())"))
    try:
        uptime = float(pathlib.Path("/proc/uptime").read_text().split()[0])
    except OSError:
        uptime = 0.0
    redis_mem = (await kv().info("memory")).get("used_memory", 0)
    return {
        "cpu": round(100 * (1 - (i2 - i1) / (t2 - t1)), 1) if t2 > t1 else None,
        "load": os.getloadavg(),
        "memory": {"total": mem.get("MemTotal", 0), "available": mem.get("MemAvailable", 0)},
        "disk": {"total": disk.total, "free": disk.free},
        "uptime": uptime,
        "db": db,
        "redis": redis_mem,
        "broker": await kv().hgetall("mqtt:sys"),
    }


async def info(s: AsyncSession) -> dict[str, Any]:
    try:
        await s.execute(text("select 1"))
        db_ok = True
    except Exception:
        db_ok = False
    try:
        redis_ok = bool(await kv().ping())
    except Exception:
        redis_ok = False
    z2m = await get_json("z2m:info", {}) or {}
    exts = [
        {"id": x.id, "name": x.name, "version": x.version, "status": x.status}
        for x in (await s.scalars(select(Extension))).all()
    ]
    return {
        "versions": {
            "core": version("valo"),
            "python": platform.python_version(),
            "web": env("WEB_VERSION", version("valo")),
            "zigbee2mqtt": z2m.get("version"),
            "mosquitto": await kv().hget("mqtt:sys", "version"),
        },
        "health": {
            "db": db_ok,
            "redis": redis_ok,
            "mqtt": await alive("mqtt"),
            "ws": await alive("ws"),
            "worker": await alive("worker"),
            "ext": await alive("ext"),
            "zigbee": await kv().get("z2m:state") or "unknown",
        },
        "extensions": exts,
        "errors": await errors_unseen(),
        "time": time.time(),
    }


async def update_check() -> dict[str, Any]:
    current = version("valo")
    if not UPDATE_URL:
        return {"current": current, "latest": None}

    def fetch() -> dict[str, Any]:
        with urllib.request.urlopen(UPDATE_URL, timeout=5) as r:
            return json.loads(r.read())

    try:
        data = await asyncio.to_thread(fetch)
    except Exception as e:
        _log.warning("update_check_failed", error=str(e))
        return {"current": current, "latest": None, "error": "unreachable"}
    return {"current": current, "latest": data.get("core"), "notes": data.get("notes")}


class ErrorReportIn(S):
    source: str
    message: str
    stack: str = ""
    url: str = ""


async def errors(p: Principal, limit: int = 200) -> dict[str, Any]:
    p.need("admin")
    ids = await kv().zrevrange(errlog.INDEX, 0, limit - 1)
    raw = await kv().hmget(errlog.ITEMS, ids) if ids else []
    items = [json.loads(x) for x in raw if x]
    seen = float(await kv().get(errlog.SEEN) or 0)
    return {"items": items, "seen": seen, "unseen": sum(1 for x in items if x["last"] > seen)}


async def errors_unseen() -> int:
    seen = float(await kv().get(errlog.SEEN) or 0)
    return await kv().zcount(errlog.INDEX, f"({seen}", "+inf")


async def errors_seen(p: Principal) -> None:
    p.need("admin")
    await kv().set(errlog.SEEN, time.time())


async def errors_clear(p: Principal) -> None:
    p.need("admin")
    await kv().delete(errlog.ITEMS, errlog.INDEX)


FOREIGN = (
    "chrome-extension://",
    "moz-extension://",
    "safari-extension://",
    "safari-web-extension://",
    "webkit-masked-url://",
)


def foreign(message: str, stack: str) -> bool:
    """Ошибка чужого скрипта в браузере: расширения браузера или скрипт с другого адреса без своих кадров стека."""
    if message.strip() in ("Script error.", "Script error"):
        return True
    return any(x in stack for x in FOREIGN) and "/_app/" not in stack


async def error_report(p: Principal, data: ErrorReportIn) -> None:
    if data.source not in ("browser", "web"):
        raise ApplicationError("validation", 422, detail="source")
    if data.source == "browser" and foreign(data.message, data.stack):
        _log.info("browser_error_ignored", reason="foreign script", message=data.message[:120])
        return
    if not await hit(f"errors:report:{p.id}", 30, 60):
        raise ApplicationError("rate_limited", 429)
    message = data.message.strip()[:300] or "error"
    item = errlog.entry(
        data.source,
        data.url.split("?")[0][:200] or data.source,
        message,
        "error",
        json.dumps({"url": data.url[:500], "user": p.username}, ensure_ascii=False),
        data.stack[:6000],
        time.time(),
    )
    raw = await kv().hget(errlog.ITEMS, item["id"])
    cur = errlog.merge(json.loads(raw) if raw else None, item)
    await kv().hset(errlog.ITEMS, item["id"], json.dumps(cur, default=str))
    await kv().zadd(errlog.INDEX, {item["id"]: cur["last"]})
