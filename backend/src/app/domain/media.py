import os
import pathlib
import shutil
import uuid
from datetime import datetime, timedelta
from typing import Any

import msgspec
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import after, now
from app.db.models import Camera, Device, Media
from app.domain import events
from app.domain.common import Principal, S, iso
from app.lib import log, realtime
from app.lib.errors import ApplicationError
from app.lib.settings import env
from app.lib.timeutil import zone

GB = 1024**3
DEFAULTS: dict[str, Any] = {"dir": "valo-media", "min_free_gb": 10.0, "days": 30, "max_gb": 0.0}
LOW_KEY = "media:low_space"
CONTINUOUS = "continuous"
_log = log.get("media")


def root() -> pathlib.Path:
    return pathlib.Path(env("MEDIA_DIR", "/media-root"))


def host_root() -> str:
    return env("MEDIA_ROOT_HOST", "")


class MediaOut(S):
    id: str
    camera_id: str | None
    event_id: int | None
    kind: str
    size: int
    duration: float | None
    origin: str
    created_at: str | None
    url: str
    meta: dict[str, Any] = {}
    thumb: str | None = None
    keep: bool = False


class BulkIn(S):
    ids: list[str] = []
    camera: str = ""
    day: str = ""
    all: bool = False


class KeepIn(S):
    keep: bool


class StorageIn(S):
    dir: str | msgspec.UnsetType = msgspec.UNSET
    min_free_gb: float | msgspec.UnsetType = msgspec.UNSET
    days: int | msgspec.UnsetType = msgspec.UNSET
    max_gb: float | msgspec.UnsetType = msgspec.UNSET


def view(m: Media) -> MediaOut:
    return MediaOut(
        id=str(m.id),
        camera_id=m.camera_id,
        event_id=m.event_id,
        kind=m.kind,
        size=m.size,
        duration=m.duration,
        origin=m.origin,
        created_at=iso(m.created_at),
        url=f"/api/v1/media/{m.id}/file",
        meta=m.meta or {},
        keep=bool(m.keep),
    )


def inside(rel: str) -> pathlib.Path:
    base = root().resolve()
    clean = str(rel or "").strip().strip("/")
    p = (base / clean).resolve()
    if p != base and base not in p.parents:
        raise ApplicationError("media_dir_invalid", 422)
    return p


async def conf(s: AsyncSession) -> dict[str, Any]:
    h = await events.home(s)
    return {**DEFAULTS, **((h.settings or {}).get("media") or {})}


async def directory(s: AsyncSession) -> pathlib.Path:
    return inside((await conf(s))["dir"])


def disk(p: pathlib.Path) -> dict[str, int]:
    probe = p
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        u = shutil.disk_usage(probe)
    except OSError as e:
        _log.warning("disk_usage_failed", path=str(probe), error=str(e))
        return {"free": 0, "total": 0}
    return {"free": u.free, "total": u.total}


def writable(p: pathlib.Path) -> bool:
    try:
        p.mkdir(parents=True, exist_ok=True)
        probe = p / f".valo-write-{uuid.uuid4().hex[:8]}"
        probe.write_bytes(b"")
        probe.unlink()
        return True
    except OSError as e:
        _log.warning("media_dir_not_writable", path=str(p), error=str(e))
        return False


def host_path(p: pathlib.Path) -> str:
    rel = p.relative_to(root().resolve()) if p.is_relative_to(root().resolve()) else p
    h = host_root()
    return f"{h.rstrip('/')}/{rel}".rstrip("/.") if h else str(p)


async def used(s: AsyncSession, rotatable: bool = False) -> tuple[int, int]:
    st = select(func.count(Media.id), func.coalesce(func.sum(Media.size), 0))
    if rotatable:
        st = st.where(Media.keep.is_(False))
    n, total = (await s.execute(st)).one()
    return int(n), int(total)


async def storage(s: AsyncSession, p: Principal) -> dict[str, Any]:
    p.need("member")
    c = await conf(s)
    d = inside(c["dir"])
    sp = disk(d)
    n, total = await used(s)
    _, free_part = await used(s, rotatable=True)
    return {
        "kept": total - free_part,
        "dir": c["dir"],
        "minFreeGb": c["min_free_gb"],
        "days": c["days"],
        "maxGb": c["max_gb"],
        "path": host_path(d),
        "root": host_root() or str(root()),
        "free": sp["free"],
        "total": sp["total"],
        "used": total,
        "count": n,
        "low": sp["free"] < float(c["min_free_gb"]) * GB,
        "writable": os.access(d if d.exists() else d.parent, os.W_OK),
    }


async def configure(s: AsyncSession, p: Principal, data: StorageIn) -> dict[str, Any]:
    p.need("admin")
    h = await events.home(s)
    cur = {**DEFAULTS, **((h.settings or {}).get("media") or {})}
    if data.dir is not msgspec.UNSET:
        d = inside(data.dir)
        if not writable(d):
            raise ApplicationError("media_dir_not_writable", 422, path=host_path(d))
        cur["dir"] = str(d.relative_to(root().resolve())) if d != root().resolve() else ""
    if data.min_free_gb is not msgspec.UNSET:
        cur["min_free_gb"] = max(1.0, min(float(data.min_free_gb), 10000.0))
    if data.days is not msgspec.UNSET:
        cur["days"] = max(0, min(int(data.days), 3650))
    if data.max_gb is not msgspec.UNSET:
        cur["max_gb"] = max(0.0, min(float(data.max_gb), 100000.0))
    h.settings = {**(h.settings or {}), "media": cur}
    await events.add(s, "media.configured", actor=p.actor, params={"path": host_path(inside(cur["dir"]))})
    return await storage(s, p)


def file_of(m: Media) -> pathlib.Path:
    return root() / m.path


async def save(
    s: AsyncSession,
    camera_id: str | None,
    kind: str,
    data: bytes | pathlib.Path,
    origin: str,
    event_id: int | None = None,
    duration: float | None = None,
    meta: dict[str, Any] | None = None,
    label: str = "",
) -> Media:
    d = await directory(s)
    ts = now()
    local = ts.astimezone(zone((await events.home(s)).timezone))
    ext = "jpg" if kind == "photo" else "mp4"
    rel_dir = pathlib.Path(camera_id or "other") / local.strftime("%Y-%m-%d")
    target = d / rel_dir
    target.mkdir(parents=True, exist_ok=True)
    name = f"{local.strftime('%H%M%S')}-{label or kind}-{uuid.uuid4().hex[:6]}.{ext}"
    f = target / name
    if isinstance(data, bytes):
        f.write_bytes(data)
    else:
        shutil.move(str(data), f)
    m = Media(
        camera_id=camera_id,
        event_id=event_id,
        kind=kind,
        path=str(f.resolve().relative_to(root().resolve())),
        size=f.stat().st_size,
        duration=duration,
        origin=origin[:160],
        meta=meta or {},
        created_at=ts,
    )
    s.add(m)
    await s.flush()
    out = view(m)
    after(s, lambda: realtime.emit("media", msgspec.to_builtins(out), ["all"], durable=False))
    return m


async def known(s: AsyncSession, f: pathlib.Path) -> bool:
    rel = str(f.resolve().relative_to(root().resolve()))
    return bool(await s.scalar(select(Media.id).where(Media.path == rel)))


async def register(
    s: AsyncSession,
    camera_id: str,
    f: pathlib.Path,
    origin: str,
    duration: float | None,
    started: datetime,
    meta: dict[str, Any] | None = None,
) -> Media | None:
    """Учесть файл, который уже записан в папку записей (постоянная запись)."""
    rel = str(f.resolve().relative_to(root().resolve()))
    if await s.scalar(select(Media.id).where(Media.path == rel)):
        return None
    m = Media(
        camera_id=camera_id,
        kind="video",
        path=rel,
        size=f.stat().st_size,
        duration=duration,
        origin=origin[:160],
        meta=meta or {},
        created_at=started,
    )
    s.add(m)
    await s.flush()
    out = view(m)
    after(s, lambda: realtime.emit("media", msgspec.to_builtins(out), ["all"], durable=False))
    return m


async def _camera_room(s: AsyncSession, camera_id: str | None) -> str | None:
    if not camera_id:
        return None
    return await s.scalar(
        select(Device.room_id).join(Camera, Camera.device_id == Device.id).where(Camera.id == camera_id)
    )


async def listing(
    s: AsyncSession,
    p: Principal,
    camera: str = "",
    kind: str = "",
    day: str = "",
    before: str = "",
    limit: int = 60,
) -> list[MediaOut]:
    p.need("member")
    st = select(Media).order_by(Media.created_at.desc()).limit(max(1, min(limit, 200)))
    if camera:
        p.need_room(await _camera_room(s, camera))
        st = st.where(Media.camera_id == camera)
    elif p.rooms:
        allowed = select(Camera.id).join(Device, Camera.device_id == Device.id).where(Device.room_id.in_(p.rooms))
        st = st.where(Media.camera_id.in_(allowed))
    if kind in ("photo", "video"):
        st = st.where(Media.kind == kind)
    if day:
        start, end = await day_range(s, day)
        st = st.where(Media.created_at >= start, Media.created_at < end)
    if before:
        try:
            st = st.where(Media.created_at < datetime.fromisoformat(before))
        except ValueError as e:
            raise ApplicationError("validation", 422, detail="before") from e
    rows = (await s.scalars(st)).all()
    events_ = {m.event_id for m in rows if m.kind == "video" and m.event_id is not None}
    photos: dict[int, str] = {}
    if events_:
        for m in (await s.scalars(select(Media).where(Media.kind == "photo", Media.event_id.in_(events_)))).all():
            photos.setdefault(m.event_id, f"/api/v1/media/{m.id}/file")
    out = []
    for m in rows:
        o = view(m)
        o.thumb = o.url if m.kind == "photo" else photos.get(m.event_id) if m.event_id is not None else None
        out.append(o)
    return out


async def get(s: AsyncSession, p: Principal, media_id: str) -> tuple[Media, pathlib.Path]:
    p.need("member")
    try:
        mid = uuid.UUID(media_id)
    except ValueError as e:
        raise ApplicationError("not_found", 404) from e
    m = await s.get(Media, mid)
    if m is None:
        raise ApplicationError("not_found", 404)
    p.need_room(await _camera_room(s, m.camera_id))
    f = file_of(m)
    if not f.is_file():
        raise ApplicationError("media_file_missing", 404)
    return m, f


async def day_range(s: AsyncSession, day: str) -> tuple[datetime, datetime]:
    """Границы суток day (ГГГГ-ММ-ДД) по часовому поясу дома."""
    try:
        d = datetime.strptime(day, "%Y-%m-%d").date()
    except ValueError as e:
        raise ApplicationError("validation", 422, detail="day") from e
    tz = zone((await events.home(s)).timezone)
    start = datetime.combine(d, datetime.min.time(), tz)
    return start, datetime.combine(d + timedelta(days=1), datetime.min.time(), tz)


async def days(s: AsyncSession, p: Principal, camera: str = "", limit: int = 120) -> list[dict[str, Any]]:
    """Дни с записями по часовому поясу дома, для календаря."""
    p.need("member")
    tz = (await events.home(s)).timezone or "UTC"
    local = func.date(func.timezone(tz, Media.created_at))
    st = (
        select(
            local.label("day"),
            func.count().filter(Media.kind == "photo"),
            func.count().filter(Media.kind == "video"),
            func.coalesce(func.sum(Media.size), 0),
        )
        .group_by(local)
        .order_by(local.desc())
        .limit(max(1, min(limit, 400)))
    )
    if camera:
        p.need_room(await _camera_room(s, camera))
        st = st.where(Media.camera_id == camera)
    elif p.rooms:
        allowed = select(Camera.id).join(Device, Camera.device_id == Device.id).where(Device.room_id.in_(p.rooms))
        st = st.where(Media.camera_id.in_(allowed))
    return [
        {"day": str(d), "photos": int(ph), "videos": int(vi), "size": int(sz)}
        for d, ph, vi, sz in (await s.execute(st)).all()
    ]


async def set_keep(s: AsyncSession, p: Principal, media_id: str, keep: bool) -> MediaOut:
    p.need("admin")
    m, _ = await get(s, p, media_id)
    m.keep = keep
    out = view(m)
    after(s, lambda: realtime.emit("media", msgspec.to_builtins(out), ["all"], durable=False))
    return out


async def remove_many(s: AsyncSession, p: Principal, data: BulkIn) -> dict[str, int]:
    """Удалить выбранные записи, записи камеры за день или все записи камеры. Сохраненные при удалении
    за день и целиком остаются, их можно удалить только по одной или выбором."""
    from app.db.models import CameraEvent

    p.need("admin")
    if data.ids:
        mids = []
        for i in data.ids[:500]:
            try:
                mids.append(uuid.UUID(i))
            except ValueError as e:
                raise ApplicationError("validation", 422, detail="ids") from e
        rows = list((await s.scalars(select(Media).where(Media.id.in_(mids)))).all())
        for m in rows:
            p.need_room(await _camera_room(s, m.camera_id))
        skipped = 0
    elif data.camera and (data.day or data.all):
        p.need_room(await _camera_room(s, data.camera))
        st = select(Media).where(Media.camera_id == data.camera)
        ev = select(CameraEvent).where(CameraEvent.camera_id == data.camera)
        if data.day:
            start, end = await day_range(s, data.day)
            st = st.where(Media.created_at >= start, Media.created_at < end)
            ev = ev.where(CameraEvent.started_at >= start, CameraEvent.started_at < end)
        found = list((await s.scalars(st)).all())
        rows = [m for m in found if not m.keep]
        skipped = len(found) - len(rows)
        kept_ids = {m.id for m in found if m.keep}
        for e in (await s.scalars(ev)).all():
            if e.snapshot_id not in kept_ids and e.clip_id not in kept_ids and e.ended_at is not None:
                await s.delete(e)
    else:
        raise ApplicationError("validation", 422, detail="ids")
    size = 0
    gone = []
    for m in rows:
        size += m.size
        gone.append(str(m.id))
        await s.delete(m)
    files = list(rows)
    after(s, lambda: unlink_all(files))
    await s.flush()
    if gone:
        await events.add(
            s,
            "media.deleted",
            actor=p.actor,
            params={"n": len(gone), "size": round(size / 1024**2, 1), "camera": data.camera or ""},
        )
        after(s, lambda: realtime.emit("media_gone", {"ids": gone}, ["all"], durable=False))
    return {"deleted": len(gone), "skipped": skipped, "size": size}


def zip_to(files: list[tuple[str, pathlib.Path]], target: pathlib.Path) -> None:
    import zipfile

    with zipfile.ZipFile(target, "w", zipfile.ZIP_STORED, allowZip64=True) as z:
        for name, f in files:
            z.write(f, name)


ZIP_MAX = 2 * GB


async def bundle(s: AsyncSession, p: Principal, ids: list[str]) -> list[tuple[str, pathlib.Path]]:
    """Файлы выбранных записей для архива, имена по камере и дню."""
    out: list[tuple[str, pathlib.Path]] = []
    total = 0
    for i in ids[:300]:
        m, f = await get(s, p, i)
        total += m.size
        if total > ZIP_MAX:
            raise ApplicationError("media_zip_too_big", 413, max=2)
        out.append((m.path.split("/", 1)[-1] if "/" in m.path else m.path, f))
    if not out:
        raise ApplicationError("validation", 422, detail="ids")
    return out


async def unlink_all(rows: list[Media]) -> None:
    for m in rows:
        unlink(m)


def unlink(m: Media) -> None:
    try:
        file_of(m).unlink()
    except FileNotFoundError:
        _log.warning("media_file_already_gone", id=str(m.id), path=m.path)
    except OSError as e:
        _log.error("media_unlink_failed", id=str(m.id), path=m.path, error=str(e))


async def remove(s: AsyncSession, p: Principal, media_id: str) -> None:
    p.need("admin")
    m, _ = await get(s, p, media_id)
    await s.delete(m)
    after(s, lambda: unlink_all([m]))
    mid = str(m.id)
    after(s, lambda: realtime.emit("media_gone", {"id": mid}, ["all"], durable=False))


async def _drop_oldest(s: AsyncSession, n: int) -> int:
    rows = (await s.scalars(select(Media).where(Media.keep.is_(False)).order_by(Media.created_at).limit(n))).all()
    for m in rows:
        unlink(m)
        await s.delete(m)
    await s.flush()
    return len(rows)


async def rotate(s: AsyncSession) -> dict[str, Any]:
    """Удалить старые записи по сроку, по лимиту объема и пока свободного места меньше порога.

    Возвращает low=True, если после удаления всего своего места все равно меньше порога, тогда видео не пишется.
    """
    c = await conf(s)
    d = inside(c["dir"])
    deleted = 0
    if int(c["days"]) > 0:
        old = (
            await s.scalars(
                select(Media)
                .where(Media.keep.is_(False), Media.created_at < now() - timedelta(days=int(c["days"])))
                .limit(500)
            )
        ).all()
        for m in old:
            unlink(m)
            await s.delete(m)
        deleted += len(old)
        await s.flush()
    for cid, rec in (await s.execute(select(Camera.id, Camera.record))).all():
        keep_days = int((rec or {}).get("keep_days") or 7)
        old = (
            await s.scalars(
                select(Media)
                .where(
                    Media.camera_id == cid,
                    Media.origin == CONTINUOUS,
                    Media.keep.is_(False),
                    Media.created_at < now() - timedelta(days=keep_days),
                )
                .limit(500)
            )
        ).all()
        for m in old:
            unlink(m)
            await s.delete(m)
        deleted += len(old)
    await s.flush()
    if float(c["max_gb"]) > 0:
        while (await used(s, rotatable=True))[1] > float(c["max_gb"]) * GB:
            k = await _drop_oldest(s, 20)
            if not k:
                break
            deleted += k
    need = float(c["min_free_gb"]) * GB
    while disk(d)["free"] < need:
        k = await _drop_oldest(s, 10)
        if not k:
            break
        deleted += k
    free = disk(d)["free"]
    low = free < need
    if deleted:
        _log.info("media_rotated", deleted=deleted, free_gb=round(free / GB, 1))
        await events.add(s, "media.rotated", params={"n": deleted, "free": round(free / GB, 1)})
    if low:
        await events.notify(
            s, LOW_KEY, "warn", "media_low_space", {"free": round(free / GB, 1), "min": c["min_free_gb"]}, "cameras"
        )
    else:
        await events.resolve(s, LOW_KEY)
    return {"low": low, "free": free, "deleted": deleted}


async def low(s: AsyncSession) -> bool:
    c = await conf(s)
    return disk(inside(c["dir"]))["free"] < float(c["min_free_gb"]) * GB
