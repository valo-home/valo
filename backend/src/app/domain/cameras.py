import base64
import json
import re
import time
import uuid
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import msgspec
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import after, commit, now, rollback, session
from app.db.models import Camera, CameraEvent, Device, Extension, Media
from app.domain import devices, events, extensions, media
from app.domain.common import Principal, S, iso, slug
from app.lib import log, realtime, rtc, secretbox, tasks
from app.lib.errors import ApplicationError
from app.lib.kv import kv
from app.lib.settings import env

CHANGED = "cameras:changed"
EVENTS = "cameras:events"
JOBS = "cameras:jobs"
TIME_SET = "cameras:time:"
PERM = "cameras.provide"
REPROBE_RETRY = (30.0, 900.0)
RECORD: dict[str, Any] = {
    "mode": "events",
    "pre": 5,
    "post": 10,
    "max": 120,
    "labels": [],
    "stream": "main",
    "schedule": {"mode": "always", "from": "22:00", "to": "07:00"},
    "keep_days": 7,
    "offline_min": 5,
    "audio": True,
    "detect": {"enabled": False, "labels": ["person", "car", "animal"], "score": 0.55},
    "zones": [],
}
MODES = ("off", "events", "continuous")
DETECT_LABELS = ("person", "car", "animal", "bicycle", "motorcycle", "truck", "bus")
_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
LABEL_CAP = {"motion": "occ"}
SCHEMES = ("rtsp://", "rtsps://", "http://", "https://", "rtmp://")
RTC_PATHS = {f"{rtc.BASE}/api/ws", f"{rtc.BASE}/api/frame.jpeg", f"{rtc.BASE}/api/stream.mp4"}
STALE = 900
STARTING = 180
VIDEO = "cameras:video:"
FEATURES = ("settings", "actions", "diagnose", "discover", "ptz")
REASONS = ("ok", "offline", "unreachable", "other_device", "auth_api", "auth_stream", "no_video", "starting")
ACTIONS_ADMIN = ("reboot", "restart_stream", "sync_time")
FIELD_TYPES = ("bool", "int", "select", "text", "info")
_log = log.get("cameras")
_stills: dict[str, tuple[float, bytes]] = {}


class DriverOut(S):
    id: str
    name: Any
    icon: str
    status: str
    fields: list[dict[str, Any]]


class CameraOut(S):
    id: str
    device_id: str
    name: str
    room_id: str | None
    driver: str
    driver_name: Any
    available: bool
    state: dict[str, Any]
    info: dict[str, Any]
    record: dict[str, Any]
    config: dict[str, Any]
    secrets: list[str]
    streams: list[str]
    stills: list[str]
    sort: int
    created_at: str | None
    features: list[str] = []
    status: dict[str, Any] = {}
    video: dict[str, Any] = {}
    presets: list[dict[str, Any]] = []
    ptz: bool = False


class EventOut(S):
    id: int
    camera_id: str
    label: str
    source: str
    score: float | None
    started_at: str | None
    ended_at: str | None
    snapshot: str | None
    clip: str | None
    data: dict[str, Any] = {}


class CameraIn(S):
    driver: str
    name: str
    config: dict[str, Any] = {}
    room_id: str | None = None
    record: dict[str, Any] | None = None


class CameraPatch(S):
    name: str | msgspec.UnsetType = msgspec.UNSET
    room_id: str | msgspec.UnsetType | None = msgspec.UNSET
    config: dict[str, Any] | msgspec.UnsetType = msgspec.UNSET
    record: dict[str, Any] | msgspec.UnsetType = msgspec.UNSET
    sort: int | msgspec.UnsetType = msgspec.UNSET


class ProbeIn(S):
    driver: str
    config: dict[str, Any] = {}


class TestIn(S):
    config: dict[str, Any] = {}


class SettingsIn(S):
    values: dict[str, Any]


class ActionIn(S):
    action: str
    params: dict[str, Any] = {}


class PresetIn(S):
    name: str = ""


def device_id(driver: str, camera_id: str) -> str:
    return slug(f"{driver.rsplit('.', 1)[-1]}-{camera_id}", "dev")


def fields_of(x: Extension) -> list[dict[str, Any]]:
    spec = x.manifest.get("camera") or {}
    return [f for f in spec.get("fields", []) if isinstance(f, dict) and f.get("key")]


def secret_keys(x: Extension) -> set[str]:
    return {f["key"] for f in fields_of(x) if f.get("type") == "secret"}


def plain_config(x: Extension | None, config: dict[str, Any]) -> dict[str, Any]:
    keys = secret_keys(x) if x else set()
    return {k: (secretbox.open_(v) if k in keys else v) for k, v in (config or {}).items()}


def _num(v: Any, lo: float, hi: float, cast: type = int) -> Any:
    try:
        return cast(max(lo, min(float(v), hi)))
    except (TypeError, ValueError) as e:
        raise ApplicationError("validation", 422, detail="record") from e


def _labels(v: Any) -> list[str]:
    if not isinstance(v, list):
        raise ApplicationError("validation", 422, detail="labels")
    return sorted({slug(str(x), "motion")[:32] for x in v if str(x).strip()})[:16]


def _zones(v: Any) -> list[dict[str, Any]]:
    if not isinstance(v, list):
        raise ApplicationError("validation", 422, detail="zones")
    out = []
    for i, z in enumerate(v[:8]):
        if not isinstance(z, dict) or not isinstance(z.get("points"), list):
            raise ApplicationError("validation", 422, detail="zones")
        pts = []
        for pt in z["points"][:16]:
            if not isinstance(pt, (list, tuple)) or len(pt) != 2:
                raise ApplicationError("validation", 422, detail="zones")
            pts.append([round(_num(pt[0], 0, 1, float), 4), round(_num(pt[1], 0, 1, float), 4)])
        if len(pts) < 3:
            raise ApplicationError("validation", 422, detail="zones")
        out.append(
            {
                "id": slug(str(z.get("id") or f"z{i + 1}"), "zone")[:24],
                "name": str(z.get("name") or "").strip()[:40],
                "kind": "exclude" if z.get("kind") == "exclude" else "include",
                "points": pts,
            }
        )
    return out


def norm_record(raw: dict[str, Any] | None, base: dict[str, Any] | None = None) -> dict[str, Any]:
    r = {**RECORD, **(base or {})}
    for k, v in (raw or {}).items():
        if k == "mode" and v in MODES:
            r["mode"] = v
        elif k in ("pre", "post"):
            r[k] = _num(v, 0, 30)
        elif k == "max":
            r[k] = _num(v, 10, 600)
        elif k == "labels":
            r["labels"] = _labels(v)
        elif k == "audio":
            r["audio"] = bool(v)
        elif k == "stream" and v in ("main", "sub"):
            r["stream"] = v
        elif k == "keep_days":
            r["keep_days"] = _num(v, 1, 365)
        elif k == "offline_min":
            r["offline_min"] = _num(v, 0, 1440)
        elif k == "schedule" and isinstance(v, dict):
            sc = {**RECORD["schedule"], **(r.get("schedule") or {})}
            if v.get("mode") in ("always", "hours"):
                sc["mode"] = v["mode"]
            for e in ("from", "to"):
                if e in v:
                    if not isinstance(v[e], str) or not _HHMM.match(v[e]):
                        raise ApplicationError("validation", 422, detail=f"schedule.{e}")
                    sc[e] = v[e]
            r["schedule"] = sc
        elif k == "detect" and isinstance(v, dict):
            dt = {**RECORD["detect"], **(r.get("detect") or {})}
            if "enabled" in v:
                dt["enabled"] = bool(v["enabled"])
            if "labels" in v:
                dt["labels"] = [x for x in _labels(v["labels"]) if x in DETECT_LABELS]
            if "score" in v:
                dt["score"] = round(_num(v["score"], 0.2, 0.95, float), 2)
            r["detect"] = dt
        elif k == "zones":
            r["zones"] = _zones(v)
    return r


def scheduled(record: dict[str, Any], at: datetime) -> bool:
    """Попадает ли местное время at в расписание записи камеры."""
    sc = record.get("schedule") or {}
    if sc.get("mode") != "hours":
        return True
    hm = at.strftime("%H:%M")
    a, b = str(sc.get("from") or "00:00"), str(sc.get("to") or "00:00")
    return a <= hm < b if a <= b else hm >= a or hm < b


def wants_label(record: dict[str, Any], label: str) -> bool:
    labels = record.get("labels") or []
    return not labels or label in labels or label == "clip"


async def drivers(s: AsyncSession) -> list[DriverOut]:
    rows = (await s.scalars(select(Extension).order_by(Extension.id))).all()
    return [
        DriverOut(
            id=x.id,
            name=x.manifest.get("name") or x.name,
            icon=x.manifest.get("icon") or "camera",
            status=x.status,
            fields=fields_of(x),
        )
        for x in rows
        if x.manifest.get("camera") and PERM in x.grants and x.enabled
    ]


async def _driver(s: AsyncSession, driver: str) -> Extension:
    x = await s.get(Extension, driver)
    if x is None or not x.manifest.get("camera") or PERM not in x.grants:
        raise ApplicationError("camera_driver_unknown", 422, driver=driver)
    if not x.enabled or x.status != "running":
        raise ApplicationError("camera_driver_stopped", 503, driver=x.name)
    return x


def _merge(x: Extension, old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    known = {f["key"]: f for f in fields_of(x)}
    out = {k: v for k, v in (old or {}).items() if k in known}
    for k, v in (new or {}).items():
        f = known.get(k)
        if f is None:
            continue
        if f.get("type") == "secret":
            if v is None:
                out[k] = ""
            elif v != "":
                out[k] = secretbox.seal(str(v))
            continue
        if f.get("type") == "number":
            try:
                out[k] = float(v) if v not in (None, "") else None
            except (TypeError, ValueError) as e:
                raise ApplicationError("validation", 422, detail=k) from e
            continue
        out[k] = v if isinstance(v, (bool, int, float)) or v is None else str(v).strip()[:500]
    for k, f in known.items():
        if f.get("required") and out.get(k) in (None, "") and f.get("default") in (None, ""):
            raise ApplicationError("camera_field_required", 422, field=k)
    return out


def _seal_urls(group: Any) -> dict[str, str]:
    res = {}
    for k, v in (group or {}).items() if isinstance(group, dict) else []:
        if isinstance(v, str) and v and v.startswith(SCHEMES) and k in ("main", "sub", "snapshot", "preview"):
            res[k] = secretbox.seal(v)
    return res


def _caps(probe: dict[str, Any]) -> list[dict[str, Any]]:
    caps = [{"id": "occ", "type": "bool", "access": "r"}]
    for c in probe.get("caps") or []:
        if isinstance(c, dict) and c.get("id") and c["id"] != "occ":
            cap = {"id": str(c["id"])[:32], "type": c.get("type", "bool"), "access": str(c.get("access", "r"))}
            cap.update({k: c[k] for k in ("unit", "min", "max", "step", "values") if k in c})
            caps.append(cap)
    return caps


async def _probe(s: AsyncSession, x: Extension, config: dict[str, Any]) -> dict[str, Any]:
    res = await extensions.rpc(s, x.id, "camera.probe", {"config": plain_config(x, config)}, timeout=25)
    if not isinstance(res, dict) or not isinstance(res.get("streams"), dict) or not res["streams"].get("main"):
        raise ApplicationError("camera_probe_failed", 422, detail="driver returned no main stream")
    if not str(res["streams"]["main"]).startswith(SCHEMES):
        raise ApplicationError("camera_probe_failed", 422, detail="unsupported stream address")
    return res


async def probe(s: AsyncSession, p: Principal, data: ProbeIn) -> dict[str, Any]:
    p.need("admin")
    x = await _driver(s, data.driver)
    res = await _probe(s, x, _merge(x, {}, data.config))
    return {"info": res.get("info") or {}, "streams": sorted(res["streams"]), "stills": sorted(res.get("stills") or {})}


def features(x: Extension | None) -> list[str]:
    spec = (x.manifest.get("camera") or {}) if x else {}
    return [f for f in spec.get("features") or [] if f in FEATURES]


def status_of(c: Camera, d: Device, x: Extension | None, video: dict[str, Any] | None) -> dict[str, Any]:
    """Понятное состояние камеры: код причины, с какого времени и подробность. Порядок проверок важен."""
    h = c.health or {}
    if x is None or not x.enabled or x.status != "running":
        return {"code": "driver_stopped", "since": h.get("since"), "detail": x.status if x else ""}
    reason = h.get("reason") if h.get("reason") in REASONS else "ok"
    if reason not in ("ok", "starting"):
        return {"code": reason, "since": h.get("since"), "detail": str(h.get("detail") or "")[:200]}
    if not d.available:
        return {"code": "offline", "since": h.get("since") or iso(d.last_seen), "detail": ""}
    v = video or {}
    if v.get("state") == "no_video":
        return {"code": "no_video", "since": v.get("since"), "detail": str(v.get("error") or "")[:200]}
    if reason == "starting" and v.get("state") == "ok" and _older(h.get("since"), STARTING):
        return {"code": "ok", "since": h.get("since"), "detail": ""}
    return {"code": reason, "since": h.get("since"), "detail": ""}


def _older(at: Any, seconds: int) -> bool:
    try:
        return (now() - datetime.fromisoformat(str(at))).total_seconds() > seconds
    except ValueError:
        return True


def view(c: Camera, d: Device, x: Extension | None, video: dict[str, Any] | None = None) -> CameraOut:
    keys = secret_keys(x) if x else set()
    return CameraOut(
        id=c.id,
        device_id=d.id,
        name=d.name,
        room_id=d.room_id,
        driver=c.driver,
        driver_name=(x.manifest.get("name") or x.name) if x else c.driver,
        available=d.available,
        state=d.state or {},
        info=c.info or {},
        record=norm_record(c.record),
        config={k: v for k, v in (c.config or {}).items() if k not in keys},
        secrets=sorted(k for k in keys if (c.config or {}).get(k)),
        streams=sorted(c.streams.get("streams", {})),
        stills=sorted(c.streams.get("stills", {})),
        sort=c.sort,
        created_at=iso(c.created_at),
        features=features(x),
        status=status_of(c, d, x, video),
        video=video or {},
        presets=list(c.presets or []),
        ptz=bool((c.info or {}).get("ptz")),
    )


async def videos(ids: list[str]) -> dict[str, dict[str, Any]]:
    """Состояние видео от службы cameras: буфер, битрейт, последняя ошибка."""
    if not ids:
        return {}
    try:
        raw = await kv().mget([VIDEO + i for i in ids])
    except Exception as e:
        _log.warning("camera_video_state_unavailable", error=str(e))
        return {}
    out = {}
    for i, r in zip(ids, raw, strict=True):
        if r:
            try:
                out[i] = json.loads(r)
            except ValueError:
                continue
    return out


async def _rows(s: AsyncSession, p: Principal | None = None) -> list[tuple[Camera, Device, Extension | None]]:
    st = (
        select(Camera, Device, Extension)
        .join(Device, Camera.device_id == Device.id)
        .outerjoin(Extension, Extension.id == Camera.driver)
        .order_by(Camera.sort, Device.name)
    )
    if p is not None and p.rooms:
        st = st.where(Device.room_id.in_(p.rooms))
    return [(c, d, x) for c, d, x in (await s.execute(st)).all()]


async def listing(s: AsyncSession, p: Principal) -> list[CameraOut]:
    p.need("member")
    rows = await _rows(s, p)
    vid = await videos([c.id for c, _, _ in rows])
    return [view(c, d, x, vid.get(c.id)) for c, d, x in rows]


async def _load(s: AsyncSession, p: Principal | None, camera_id: str) -> tuple[Camera, Device, Extension | None]:
    c = await s.get(Camera, camera_id)
    if c is None:
        raise ApplicationError("camera_not_found", 404)
    d = await s.get(Device, c.device_id)
    if d is None:
        raise ApplicationError("camera_not_found", 404)
    if p is not None:
        p.need("member")
        p.need_room(d.room_id)
    return c, d, await s.get(Extension, c.driver)


load = _load


async def one(s: AsyncSession, p: Principal, camera_id: str) -> CameraOut:
    c, d, x = await _load(s, p, camera_id)
    return view(c, d, x, (await videos([c.id])).get(c.id))


async def _unique(s: AsyncSession, base: str) -> str:
    cid = base[:56]
    n = 2
    while await s.get(Camera, cid) is not None:
        cid = f"{base[:52]}-{n}"
        n += 1
    return cid


def _changed(s: AsyncSession, driver: str) -> None:
    async def push() -> None:
        await kv().publish(CHANGED, driver)
        await tasks.kick("cameras.sync_driver", driver=driver)

    after(s, push)


async def create(s: AsyncSession, p: Principal, data: CameraIn) -> CameraOut:
    p.need("admin")
    x = await _driver(s, data.driver)
    name = data.name.strip()[:120]
    if not name:
        raise ApplicationError("camera_field_required", 422, field="name")
    config = _merge(x, {}, data.config)
    res = await _probe(s, x, config)
    cid = await _unique(s, slug(name, "cam"))
    did = device_id(x.id, cid)
    if await s.get(Device, did) is not None:
        raise ApplicationError("camera_exists", 409, name=name)
    info = res.get("info") if isinstance(res.get("info"), dict) else {}
    d, _ = await devices.upsert(
        s,
        did,
        "ext",
        name,
        address=cid,
        ext_id=x.id,
        kind="camera",
        model=str(info.get("model") or "")[:160],
        vendor=str(info.get("vendor") or "")[:80],
        caps=_caps(res),
        room_id=data.room_id or None,
        attrs={"meta": {"name": name, "kind": "camera", "service": False}, "nameSet": True},
    )
    c = Camera(
        id=cid,
        device_id=d.id,
        driver=x.id,
        config=config,
        streams={"streams": _seal_urls(res.get("streams")), "stills": _seal_urls(res.get("stills"))},
        info={k: v for k, v in info.items() if isinstance(v, (str, int, float, bool))},
        record=norm_record(data.record),
        sort=len(await _rows(s)),
    )
    s.add(c)
    await s.flush()
    await events.add(
        s,
        "camera.added",
        "ok",
        actor=p.actor,
        params={"name": name, "driver": x.name},
        device_id=d.id,
        room_id=d.room_id,
    )
    _changed(s, x.id)
    return view(c, d, x)


async def update(s: AsyncSession, p: Principal, camera_id: str, data: CameraPatch) -> CameraOut:
    p.need("admin")
    c, d, x = await _load(s, p, camera_id)
    if data.name is not msgspec.UNSET and data.name.strip():
        d.name = data.name.strip()[:120]
        d.attrs = {**(d.attrs or {}), "nameSet": True}
    if data.room_id is not msgspec.UNSET:
        d.room_id = data.room_id or None
    if data.sort is not msgspec.UNSET:
        c.sort = int(data.sort)
    if data.record is not msgspec.UNSET:
        c.record = norm_record(data.record, c.record)
    if data.config is not msgspec.UNSET:
        if x is None:
            raise ApplicationError("camera_driver_unknown", 422, driver=c.driver)
        x = await _driver(s, c.driver)
        config = _merge(x, c.config, data.config)
        res = await _probe(s, x, config)
        c.config = config
        c.streams = {"streams": _seal_urls(res.get("streams")), "stills": _seal_urls(res.get("stills"))}
        info = res.get("info") if isinstance(res.get("info"), dict) else {}
        c.info = {k: v for k, v in info.items() if isinstance(v, (str, int, float, bool))}
        d.caps = _caps(res)
    await events.add(s, "camera.updated", actor=p.actor, params={"name": d.name}, device_id=d.id, room_id=d.room_id)
    snapshot = devices.view(d)
    after(s, lambda: realtime.emit("device", snapshot, devices.rooms_of(d)))
    _changed(s, c.driver)
    return view(c, d, x)


async def remove(s: AsyncSession, p: Principal, camera_id: str, keep_media: bool = True) -> int:
    """Удалить камеру. Записи остаются с именем камеры в meta или удаляются вместе с файлами."""
    p.need("admin")
    c, d, _ = await _load(s, p, camera_id)
    driver, name = c.driver, d.name
    rows = (await s.scalars(select(Media).where(Media.camera_id == c.id))).all()
    for m in rows:
        if keep_media:
            m.meta = {**(m.meta or {}), "camera": name}
        else:
            await s.delete(m)
    await s.flush()
    if not keep_media:
        files = list(rows)
        after(s, lambda: media.unlink_all(files))
    await devices.remove(s, p, d.id)
    await events.add(s, "camera.removed", actor=p.actor, params={"name": name, "n": len(rows), "kept": int(keep_media)})
    _changed(s, driver)
    return len(rows)


def _clean(v: Any) -> Any:
    return v if isinstance(v, (bool, int, float, str)) or v is None else str(v)[:200]


def norm_fields(raw: Any) -> list[dict[str, Any]]:
    """Описание настроек камеры от драйвера. Неизвестные типы и лишние ключи отбрасываются."""
    out: list[dict[str, Any]] = []
    for f in raw if isinstance(raw, list) else []:
        if not isinstance(f, dict) or not f.get("key") or f.get("type") not in FIELD_TYPES:
            continue
        item: dict[str, Any] = {
            "key": str(f["key"])[:48],
            "type": f["type"],
            "section": slug(str(f.get("section") or "other"), "other")[:24],
            "value": _clean(f.get("value")),
        }
        for k in ("min", "max", "step"):
            if isinstance(f.get(k), (int, float)) and not isinstance(f.get(k), bool):
                item[k] = f[k]
        if isinstance(f.get("options"), list):
            item["options"] = [str(o)[:32] for o in f["options"][:24]]
        if isinstance(f.get("unit"), str):
            item["unit"] = f["unit"][:12]
        if isinstance(f.get("name"), (str, dict)):
            item["name"] = f["name"]
        for k in ("readonly", "restart"):
            if f.get(k):
                item[k] = True
        out.append(item)
    return out[:80]


async def _dcall(
    s: AsyncSession, c: Camera, x: Extension | None, feature: str, params: dict[str, Any], timeout: float = 20
) -> dict[str, Any]:
    if x is None or feature not in features(x):
        raise ApplicationError("camera_feature_unsupported", 422, feature=feature)
    if not x.enabled or x.status != "running":
        raise ApplicationError("camera_driver_stopped", 503, driver=x.name)
    res = await extensions.rpc(
        s,
        x.id,
        f"camera.{feature}",
        {"camera": c.id, "config": plain_config(x, c.config), "info": c.info or {}, **params},
        timeout=timeout,
    )
    return res if isinstance(res, dict) else {}


async def settings_get(s: AsyncSession, p: Principal, camera_id: str) -> dict[str, Any]:
    c, _, x = await _load(s, p, camera_id)
    res = await _dcall(s, c, x, "settings", {"op": "get"})
    return {"fields": norm_fields(res.get("fields")), "failed": {}}


async def settings_set(s: AsyncSession, p: Principal, camera_id: str, values: dict[str, Any]) -> dict[str, Any]:
    p.need("admin")
    c, d, x = await _load(s, p, camera_id)
    clean = {str(k)[:48]: _clean(v) for k, v in (values or {}).items()}
    if not clean:
        raise ApplicationError("validation", 422, detail="values")
    res = await _dcall(s, c, x, "settings", {"op": "set", "values": clean}, timeout=30)
    failed = {str(k)[:48]: str(v)[:200] for k, v in (res.get("failed") or {}).items()}
    await events.add(
        s,
        "camera.configured",
        "warn" if failed else "info",
        actor=p.actor,
        params={"name": d.name, "keys": ", ".join(sorted(clean))[:200]},
        device_id=d.id,
        room_id=d.room_id,
    )
    return {"fields": norm_fields(res.get("fields")), "failed": failed}


async def action(s: AsyncSession, p: Principal, camera_id: str, name: str, params: dict[str, Any]) -> dict[str, Any]:
    p.need("admin" if name in ACTIONS_ADMIN else "member")
    c, d, x = await _load(s, p, camera_id)
    if name == "reconnect":
        p.need("admin")
        c.health = {**(c.health or {}), "reason": "starting", "since": iso(now()), "detail": ""}
        await rtc_reset(c.id)
        _changed(s, c.driver)
        await events.add(s, "camera.action", actor=p.actor, params={"name": d.name, "action": name}, device_id=d.id)
        return {"ok": True}
    if name not in ACTIONS_ADMIN:
        raise ApplicationError("validation", 422, detail="action")
    extra = dict(params or {})
    if name == "sync_time":
        extra.setdefault("timezone", (await events.home(s)).timezone)
        extra.setdefault("ntp", ntp_server())
    res = await _dcall(s, c, x, "actions", {"action": name, "params": extra}, timeout=30)
    await events.add(s, "camera.action", actor=p.actor, params={"name": d.name, "action": name}, device_id=d.id)
    if name == "reboot":
        c.health = {**(c.health or {}), "reason": "starting", "since": iso(now()), "detail": "reboot"}
        _changed(s, c.driver)
    return {"ok": bool(res.get("ok", True)), "detail": str(res.get("detail") or "")[:300]}


async def heal(s: AsyncSession, camera_id: str) -> str:
    """Камера на связи, но видео не приходит: перезапустить поток на камере, если драйвер не смог, переподключить."""
    c = await s.get(Camera, camera_id)
    if c is None:
        return "missing"
    d = await s.get(Device, c.device_id)
    x = await s.get(Extension, c.driver)
    if d is None or (c.health or {}).get("reason") != "ok":
        return "skipped"
    how = "restart_stream"
    try:
        await _dcall(s, c, x, "actions", {"action": how, "params": {}}, timeout=30)
    except ApplicationError as e:
        _log.warning("camera_heal_driver_failed", camera=c.id, code=e.code)
        how = "reconnect"
        await rtc_reset(c.id)
    await events.add(s, "camera.healed", "warn", params={"name": d.name, "action": how}, device_id=d.id)
    _log.warning("camera_healed", camera=c.id, how=how)
    return how


async def keep_time(s: AsyncSession) -> int:
    """Настроить время камер на узел Valo, если адрес узла или часовой пояс сменились с прошлой настройки."""
    addr = ntp_server()
    if not addr:
        return 0
    tz = (await events.home(s)).timezone or "UTC"
    want, n = f"{addr}|{tz}", 0
    for c, _, x in await _rows(s):
        if x is None or "actions" not in features(x) or (c.health or {}).get("reason") != "ok":
            continue
        key = TIME_SET + c.id
        if await kv().get(key) in (want, "retry"):
            continue
        try:
            res = await _dcall(
                s, c, x, "actions", {"action": "sync_time", "params": {"timezone": tz, "ntp": addr}}, timeout=30
            )
        except ApplicationError as e:
            _log.warning("camera_time_not_set", camera=c.id, code=e.code)
            await kv().set(key, "retry", ex=600)
            continue
        await kv().set(key, want)
        _log.info("camera_time_set", camera=c.id, ntp=addr, tz=tz, detail=str(res.get("detail") or "")[:120])
        n += 1
    return n


def ntp_server() -> str:
    """Адрес узла Valo в домашней сети для времени камер, если служба времени включена."""
    return env("VALO_NTP_ADDR", "")


async def rtc_reset(camera_id: str) -> None:
    await kv().publish(CHANGED, f"reset:{camera_id}")


async def diagnose(s: AsyncSession, p: Principal, camera_id: str) -> dict[str, Any]:
    p.need("admin")
    c, d, x = await _load(s, p, camera_id)
    vid = (await videos([c.id])).get(c.id) or {}
    checks: list[dict[str, Any]] = [
        {
            "key": "driver",
            "ok": x is not None and x.status == "running",
            "value": (x.status if x else "missing"),
            "detail": x.name if x else c.driver,
        }
    ]
    if x is not None and "diagnose" in features(x) and x.status == "running":
        try:
            res = await _dcall(s, c, x, "diagnose", {}, timeout=40)
            for ch in res.get("checks") or []:
                if isinstance(ch, dict) and ch.get("key"):
                    checks.append(
                        {
                            "key": str(ch["key"])[:32],
                            "ok": ch.get("ok") if isinstance(ch.get("ok"), bool) else None,
                            "value": _clean(ch.get("value")),
                            "detail": str(ch.get("detail") or "")[:300],
                        }
                    )
        except ApplicationError as e:
            checks.append({"key": "driver_diagnose", "ok": False, "value": e.code, "detail": ""})
    checks.append(
        {
            "key": "video_stream",
            "ok": bool(vid.get("kbps")) if vid else None,
            "value": vid.get("kbps"),
            "detail": ", ".join(vid.get("codecs") or []),
        }
    )
    rec = norm_record(c.record)
    if rec["mode"] != "off":
        age = vid.get("buffer_age")
        checks.append(
            {
                "key": "buffer",
                "ok": age is not None and age < 30,
                "value": age,
                "detail": str(vid.get("error") or "")[:300],
            }
        )
    if rec["mode"] == "continuous":
        checks.append(
            {
                "key": "continuous",
                "ok": bool(vid.get("continuous")),
                "value": vid.get("continuous_age"),
                "detail": str(vid.get("continuous_error") or "")[:300],
            }
        )
    low = await media.low(s)
    checks.append({"key": "storage", "ok": not low, "value": None, "detail": ""})
    return {"checks": checks, "status": status_of(c, d, x, vid), "at": iso(now())}


async def _relocate(s: AsyncSession, c: Camera, d: Device, x: Extension, host: str, actor: str) -> None:
    old = str((c.config or {}).get("host") or "")
    c.config = {**(c.config or {}), "host": host}
    c.health = {**(c.health or {}), "reason": "starting", "since": iso(now()), "detail": f"{old} -> {host}"}
    await events.add(
        s, "camera.moved", "warn", actor=actor, params={"name": d.name, "old": old, "new": host}, device_id=d.id
    )
    _log.warning("camera_moved", camera=c.id, old=old, new=host)


async def discover(s: AsyncSession, p: Principal, camera_id: str) -> dict[str, Any]:
    p.need("admin")
    c, d, x = await _load(s, p, camera_id)
    res = await _dcall(s, c, x, "discover", {}, timeout=60)
    found = [
        {k: _clean(f.get(k)) for k in ("host", "mac", "model", "hostname", "same")}
        for f in res.get("found") or []
        if isinstance(f, dict) and f.get("host")
    ][:32]
    match = next((f["host"] for f in found if f.get("same")), None)
    moved = False
    if match and x is not None and match != (c.config or {}).get("host"):
        await _relocate(s, c, d, x, str(match), p.actor)
        await reprobe_now(s, c, d, x)
        moved = True
    return {"found": found, "match": match, "moved": moved}


async def reprobe_now(s: AsyncSession, c: Camera, d: Device, x: Extension) -> None:
    res = await _probe(s, x, c.config)
    c.streams = {"streams": _seal_urls(res.get("streams")), "stills": _seal_urls(res.get("stills"))}
    info = res.get("info") if isinstance(res.get("info"), dict) else {}
    c.info = {k: v for k, v in info.items() if isinstance(v, (str, int, float, bool))}
    d.caps = _caps(res)
    _changed(s, c.driver)


async def reprobe(camera_id: str, attempt: int = 0) -> None:
    """Пересчитать потоки после смены адреса. Если камера еще загружается, попытка повторяется позже."""
    async with session() as s:
        c = await s.get(Camera, camera_id)
        if c is None:
            return
        d = await s.get(Device, c.device_id)
        x = await s.get(Extension, c.driver)
        if d is None or x is None:
            return
        drv = c.driver
        try:
            await reprobe_now(s, c, d, x)
        except ApplicationError as e:
            delay = min(REPROBE_RETRY[0] * 2**attempt, REPROBE_RETRY[1])
            _log.warning("camera_reprobe_failed", camera=camera_id, code=e.code, attempt=attempt, retry_in=delay)
            await rollback(s)
            _changed(s, drv)
            after(
                s,
                lambda: tasks.later(
                    f"camera_reprobe:{camera_id}", delay, "cameras.reprobe", camera=camera_id, attempt=attempt + 1
                ),
            )
        await commit(s)


async def test(s: AsyncSession, p: Principal, camera_id: str, data: TestIn) -> dict[str, Any]:
    """Проверить подключение с новыми полями без сохранения. Пустые пароли берутся из сохраненных."""
    p.need("admin")
    c, _, x = await _load(s, p, camera_id)
    if x is None:
        raise ApplicationError("camera_driver_unknown", 422, driver=c.driver)
    x = await _driver(s, c.driver)
    res = await _probe(s, x, _merge(x, c.config, data.config))
    return {"info": res.get("info") or {}, "streams": sorted(res["streams"]), "stills": sorted(res.get("stills") or {})}


async def ptz(s: AsyncSession, p: Principal, camera_id: str, params: dict[str, Any]) -> dict[str, Any]:
    p.need("member")
    c, _, x = await _load(s, p, camera_id)
    op = str(params.get("op") or "")
    if op not in ("move", "stop", "home", "goto", "position", "calibrate"):
        raise ApplicationError("validation", 422, detail="op")
    if op == "calibrate":
        p.need("admin")
    body = {"op": op}
    for k in ("pan", "tilt", "speed"):
        if isinstance(params.get(k), (int, float)) and not isinstance(params.get(k), bool):
            body[k] = max(-1.0, min(float(params[k]), 1.0)) if k != "speed" else max(0.05, min(float(params[k]), 1.0))
    if op == "goto":
        pos = params.get("position")
        if not isinstance(pos, dict):
            raise ApplicationError("validation", 422, detail="position")
        body["position"] = {k: float(v) for k, v in pos.items() if isinstance(v, (int, float))}
    res = await _dcall(s, c, x, "ptz", body, timeout=40)
    pos = res.get("position")
    return {
        "position": {k: v for k, v in pos.items() if isinstance(v, (int, float))} if isinstance(pos, dict) else None
    }


async def preset_add(s: AsyncSession, p: Principal, camera_id: str, name: str) -> list[dict[str, Any]]:
    p.need("admin")
    c, d, _ = await _load(s, p, camera_id)
    pos = (await ptz(s, p, camera_id, {"op": "position"}))["position"]
    if not pos:
        raise ApplicationError("camera_ptz_position_unknown", 422)
    items = list(c.presets or [])
    if len(items) >= 16:
        raise ApplicationError("camera_presets_full", 422, n=16)
    label = name.strip()[:40] or f"{len(items) + 1}"
    pid = slug(label, "p")[:24]
    while any(x["id"] == pid for x in items):
        pid = f"{pid[:20]}-{len(items) + 1}"
    items.append({"id": pid, "name": label, "position": pos})
    c.presets = items
    await events.add(s, "camera.preset", actor=p.actor, params={"name": d.name, "preset": label}, device_id=d.id)
    return items


async def preset_edit(
    s: AsyncSession, p: Principal, camera_id: str, pid: str, name: str | None, remove_: bool = False
) -> list[dict[str, Any]]:
    p.need("admin")
    c, _, _ = await _load(s, p, camera_id)
    items = [dict(x) for x in c.presets or []]
    if not any(x["id"] == pid for x in items):
        raise ApplicationError("not_found", 404)
    if remove_:
        items = [x for x in items if x["id"] != pid]
    else:
        for x in items:
            if x["id"] == pid and name and name.strip():
                x["name"] = name.strip()[:40]
    c.presets = items
    return items


async def preset_go(s: AsyncSession, p: Principal | None, camera_id: str, pid: str) -> dict[str, Any]:
    c, _, x = await _load(s, p, camera_id)
    pre = next((x_ for x_ in c.presets or [] if x_["id"] == pid or x_["name"] == pid), None)
    if pre is None:
        raise ApplicationError("camera_preset_unknown", 404, preset=pid)
    res = await _dcall(s, c, x, "ptz", {"op": "goto", "position": pre["position"]}, timeout=40)
    return {"position": res.get("position"), "preset": pre["id"]}


async def patrol(camera_id: str, presets: list[str], seconds: int, rounds: int) -> None:
    """Обход пресетов поворотной камеры по кругу. Новый обход той же камеры прерывает прежний."""
    import asyncio

    token = uuid.uuid4().hex
    await kv().set(f"cameras:patrol:{camera_id}", token, ex=seconds * len(presets) * rounds + 120)
    for _ in range(rounds):
        for pid in presets:
            if await kv().get(f"cameras:patrol:{camera_id}") != token:
                _log.info("patrol_replaced", camera=camera_id)
                return
            try:
                async with session() as s:
                    await preset_go(s, None, camera_id, pid)
            except ApplicationError as e:
                _log.warning("patrol_step_failed", camera=camera_id, preset=pid, code=e.code)
            await asyncio.sleep(seconds)
    _log.info("patrol_done", camera=camera_id, presets=len(presets), rounds=rounds)


async def health(s: AsyncSession, ext_id: str, params: dict[str, Any]) -> dict[str, Any]:
    """Состояние связи с камерой от ее драйвера."""
    c = await s.get(Camera, str(params.get("camera") or ""))
    if c is None:
        raise ApplicationError("camera_not_found", 404)
    if c.driver != ext_id:
        raise ApplicationError("ext_permission", 403, perm=PERM)
    reason = str(params.get("reason") or "ok")
    if reason not in REASONS:
        raise ApplicationError("validation", 422, detail="reason")
    h = dict(c.health or {})
    if h.get("reason") != reason:
        h["since"] = iso(now())
        _log.info("camera_health", camera=c.id, reason=reason, was=h.get("reason"))
    h["reason"] = reason
    h["detail"] = str(params.get("detail") or "")[:200]
    c.health = h
    d = await s.get(Device, c.device_id)
    if d is not None:
        snap = devices.view(d)
        after(s, lambda: realtime.emit("device", snap, devices.rooms_of(d)))
    return {"ok": True}


async def moved(s: AsyncSession, ext_id: str, params: dict[str, Any]) -> dict[str, Any]:
    """Драйвер нашел свою камеру по новому адресу. Адрес сохраняется, потоки пересчитываются задачей."""
    c = await s.get(Camera, str(params.get("camera") or ""))
    if c is None:
        raise ApplicationError("camera_not_found", 404)
    if c.driver != ext_id:
        raise ApplicationError("ext_permission", 403, perm=PERM)
    host = str(params.get("host") or "").strip()[:255]
    if not re.match(r"^[A-Za-z0-9.\-:\[\]]+$", host):
        raise ApplicationError("validation", 422, detail="host")
    d = await s.get(Device, c.device_id)
    x = await s.get(Extension, c.driver)
    if d is None or x is None:
        raise ApplicationError("camera_not_found", 404)
    if (c.config or {}).get("host") == host:
        _log.warning("camera_moved_again", camera=c.id, host=host)
        _changed(s, c.driver)
        return {"ok": True, "changed": False}
    await _relocate(s, c, d, x, host, f"ext:{ext_id}")
    cid = c.id
    after(s, lambda: tasks.kick("cameras.reprobe", camera=cid))
    return {"ok": True, "changed": True}


async def watch_offline(s: AsyncSession) -> None:
    """Уведомление, если камера без связи дольше offline_min минут, и снова на связи."""
    t = now()
    for c, d, x in await _rows(s):
        st = status_of(c, d, x, None)["code"]
        h = dict(c.health or {})
        key = f"camera_offline:{c.id}"
        lim = norm_record(c.record)["offline_min"]
        if st in ("offline", "unreachable", "other_device", "auth_api", "auth_stream", "driver_stopped"):
            down = h.get("down_since") or iso(t)
            h["down_since"] = down
            mins = (t - datetime.fromisoformat(str(down))).total_seconds() / 60
            if lim and not h.get("notified") and mins >= lim:
                await events.notify(
                    s, key, "warn", "camera_offline", {"name": d.name, "min": int(mins), "reason": st}, "cameras"
                )
                await events.add(s, "camera.offline", "warn", params={"name": d.name, "min": int(mins)}, device_id=d.id)
                h["notified"] = True
        elif "down_since" in h:
            if h.get("notified"):
                await events.resolve(s, key)
                await events.notify(s, f"camera_online:{c.id}", "info", "camera_online", {"name": d.name}, "cameras")
                await events.resolve(s, f"camera_online:{c.id}")
                await events.add(s, "camera.online", "ok", params={"name": d.name}, device_id=d.id)
            h.pop("down_since", None)
            h.pop("notified", None)
        if h != (c.health or {}):
            c.health = h


async def for_driver(s: AsyncSession, driver: str) -> list[dict[str, Any]]:
    x = await s.get(Extension, driver)
    rows = (await s.scalars(select(Camera).where(Camera.driver == driver).order_by(Camera.id))).all()
    return [{"id": c.id, "config": plain_config(x, c.config), "info": c.info or {}} for c in rows]


async def sync_driver(driver: str) -> None:
    async with session() as s:
        x = await s.get(Extension, driver)
        if x is None or x.status != "running":
            return
        try:
            await extensions.rpc(s, driver, "camera.sync", {"cameras": await for_driver(s, driver)}, timeout=15)
        except ApplicationError as e:
            _log.warning("camera_sync_failed", driver=driver, code=e.code)


async def sources(s: AsyncSession) -> dict[str, Any]:
    """Потоки и правила записи всех камер для службы видео. Адреса с паролями расшифровываются только здесь."""
    out: dict[str, Any] = {}
    for c, _, _ in await _rows(s):
        st = {k: str(secretbox.open_(v)) for k, v in (c.streams.get("streams") or {}).items()}
        if not st.get("main"):
            _log.error(
                "camera_stream_unreadable", camera=c.id, hint="secret key changed, edit the camera to save it again"
            )
            continue
        out[c.id] = {
            "main": st["main"],
            "sub": st.get("sub") or "",
            "record": norm_record(c.record),
        }
    return out


async def timezone(s: AsyncSession) -> str:
    return (await events.home(s)).timezone or "UTC"


def _still_url(c: Camera, sub: bool) -> str:
    stills = c.streams.get("stills") or {}
    raw = stills.get("preview" if sub else "snapshot") or stills.get("snapshot" if sub else "preview")
    return str(secretbox.open_(raw)) if raw else ""


async def still(c: Camera, sub: bool = True, fresh: bool = False, local: bool = False) -> bytes:
    key = f"{c.id}:{int(sub)}"
    hit = _stills.get(key)
    if hit and not fresh and time.monotonic() - hit[0] < 8:
        return hit[1]
    url = _still_url(c, sub)
    try:
        async with httpx.AsyncClient(timeout=8) as cl:
            if url:
                r = await cl.get(url)
            else:
                r = await cl.get(
                    rtc.api("/api/frame.jpeg", local),
                    params={"src": rtc.stream(c.id, sub and bool(c.streams.get("streams", {}).get("sub")))},
                    headers={"Authorization": rtc.auth_header()},
                )
        r.raise_for_status()
        if not r.content.startswith(b"\xff\xd8"):
            raise ValueError(f"not a jpeg, {r.headers.get('content-type')}")
    except (httpx.HTTPError, ValueError) as e:
        _log.warning("camera_still_failed", camera=c.id, via="camera" if url else "go2rtc", error=rtc.mask(str(e)))
        raise ApplicationError("camera_unavailable", 503) from e
    _stills[key] = (time.monotonic(), r.content)
    if len(_stills) > 64:
        for k in sorted(_stills, key=lambda k: _stills[k][0])[:16]:
            _stills.pop(k, None)
    return r.content


async def preview(s: AsyncSession, p: Principal, camera_id: str, full: bool = False) -> bytes:
    c, _, _ = await _load(s, p, camera_id)
    return await still(c, sub=not full)


async def capture(
    s: AsyncSession, camera_id: str, origin: str, event_id: int | None = None, label: str = "", local: bool = False
) -> media.Media:
    c, _, _ = await _load(s, None, camera_id)
    data = await still(c, sub=False, fresh=True, local=local)
    return await media.save(s, c.id, "photo", data, origin, event_id=event_id, label=label)


async def put_photo(s: AsyncSession, ext_id: str, params: dict[str, Any]) -> media.MediaOut:
    """Снимок от расширения (например кадр с рамкой распознавания). Привязывается к событию, если оно указано."""
    c, _, _ = await _load(s, None, str(params.get("camera", "")))
    try:
        data = base64.b64decode(str(params.get("data") or ""), validate=True)
    except ValueError as e:
        raise ApplicationError("validation", 422, detail="data") from e
    if not data.startswith(b"\xff\xd8") or len(data) > 10 * 1024 * 1024:
        raise ApplicationError("validation", 422, detail="data must be a JPEG up to 10 MB")
    eid = params.get("event")
    if eid is not None:
        e = await s.get(CameraEvent, int(eid)) if str(eid).isdigit() else None
        if e is None or e.camera_id != c.id:
            raise ApplicationError("not_found", 404)
    label = slug(str(params.get("label") or "ext"), "ext")[:24]
    meta = params.get("meta") if isinstance(params.get("meta"), dict) else {}
    m = await media.save(
        s, c.id, "photo", data, f"ext:{ext_id}", event_id=int(eid) if eid is not None else None, meta=meta, label=label
    )
    if eid is not None:
        await attach(s, int(eid), snapshot_id=m.id)
    return media.view(m)


async def snapshot(s: AsyncSession, p: Principal, camera_id: str) -> media.MediaOut:
    p.need("member")
    await _load(s, p, camera_id)
    return media.view(await capture(s, camera_id, p.actor, label="manual"))


async def clip(s: AsyncSession, p: Principal | None, camera_id: str, seconds: int, origin: str) -> dict[str, Any]:
    c, d, _ = await _load(s, p, camera_id)
    if await media.low(s):
        raise ApplicationError("media_low_space", 507)
    job = {"camera": c.id, "seconds": max(3, min(int(seconds), 300)), "origin": origin, "at": time.time()}
    after(s, lambda: kv().publish(JOBS, json.dumps(job)))
    await events.add(s, "camera.clip", actor=origin, params={"name": d.name, "seconds": job["seconds"]}, device_id=d.id)
    return job


def ev_view(e: CameraEvent) -> EventOut:
    return EventOut(
        id=e.id,
        camera_id=e.camera_id,
        label=e.label,
        source=e.source,
        score=e.score,
        started_at=iso(e.started_at),
        ended_at=iso(e.ended_at),
        snapshot=f"/api/v1/media/{e.snapshot_id}/file" if e.snapshot_id else None,
        clip=f"/api/v1/media/{e.clip_id}/file" if e.clip_id else None,
        data=e.data or {},
    )


async def event_list(
    s: AsyncSession,
    p: Principal,
    camera_id: str,
    before: str = "",
    label: str = "",
    limit: int = 50,
    day: str = "",
) -> list[EventOut]:
    await _load(s, p, camera_id)
    st = (
        select(CameraEvent)
        .where(CameraEvent.camera_id == camera_id)
        .order_by(CameraEvent.started_at.desc(), CameraEvent.id.desc())
        .limit(max(1, min(limit, 500)))
    )
    if label:
        st = st.where(CameraEvent.label == label)
    if day:
        start, end = await media.day_range(s, day)
        st = st.where(CameraEvent.started_at >= start, CameraEvent.started_at < end)
    if before.isdigit():
        st = st.where(CameraEvent.id < int(before))
    return [ev_view(e) for e in (await s.scalars(st)).all()]


async def event_remove(s: AsyncSession, p: Principal, camera_id: str, event_id: int) -> int:
    """Удалить событие вместе с его снимком и клипом."""
    p.need("admin")
    await _load(s, p, camera_id)
    e = await s.get(CameraEvent, event_id)
    if e is None or e.camera_id != camera_id:
        raise ApplicationError("not_found", 404)
    ids = [str(i) for i in (e.snapshot_id, e.clip_id) if i]
    await s.delete(e)
    await s.flush()
    n = (await media.remove_many(s, p, media.BulkIn(ids=ids)))["deleted"] if ids else 0
    after(s, lambda: realtime.emit("camera_event_gone", {"id": event_id, "camera": camera_id}, ["all"], durable=False))
    return n


async def report(s: AsyncSession, ext_id: str, params: dict[str, Any], grants: set[str]) -> dict[str, Any]:
    """Событие от драйвера или от расширения распознавания. active True начало, False конец, None мгновенное."""
    cid = str(params.get("camera") or "")
    c = await s.get(Camera, cid)
    if c is None:
        raise ApplicationError("camera_not_found", 404)
    if not ((c.driver == ext_id and PERM in grants) or "cameras.events" in grants):
        raise ApplicationError("ext_permission", 403, perm="cameras.events")
    d = await s.get(Device, c.device_id)
    if d is None:
        raise ApplicationError("camera_not_found", 404)
    label = slug(str(params.get("label") or "motion"), "motion")[:32]
    active = params.get("active")
    score = params.get("score")
    score = float(score) if isinstance(score, (int, float)) else None
    data = params.get("data") if isinstance(params.get("data"), dict) else {}
    source = "driver" if c.driver == ext_id else f"ext:{ext_id}"
    open_ = await s.scalar(
        select(CameraEvent)
        .where(CameraEvent.camera_id == c.id, CameraEvent.label == label, CameraEvent.ended_at.is_(None))
        .order_by(CameraEvent.started_at.desc())
    )
    ts = now()
    phase = "start"
    if active is False:
        if open_ is None:
            return {"ok": True, "event": None}
        open_.ended_at = ts
        e, phase = open_, "end"
    elif active is True and open_ is not None:
        if score is not None and (open_.score is None or score > open_.score):
            open_.score = score
        return {"ok": True, "event": open_.id}
    else:
        e = CameraEvent(
            camera_id=c.id,
            label=label,
            source=source,
            score=score,
            data=data,
            started_at=ts,
            ended_at=ts if active is None else None,
        )
        s.add(e)
        await s.flush()
        phase = "start" if active is True else "once"
    cap = LABEL_CAP.get(label, label)
    if any(x.get("id") == cap for x in d.caps or []) and active is not None:
        await devices.apply(s, d, {cap: bool(active)})
    elif active is not None and label != "motion":
        d.caps = [*(d.caps or []), {"id": cap, "type": "bool", "access": "r"}]
        await devices.apply(s, d, {cap: bool(active)})
    body = {"camera": c.id, "event": e.id, "label": label, "phase": phase, "at": time.time(), "source": e.source}
    out = msgspec.to_builtins(ev_view(e))
    rooms = devices.rooms_of(d)
    did = d.id

    async def push() -> None:
        await kv().publish(EVENTS, json.dumps(body))
        await realtime.emit("camera_event", out, rooms, durable=False)
        if await events.wants(f"camera:{did}"):
            await tasks.kick(
                "flows.dispatch",
                event={"type": "camera", "device": did, "camera": body["camera"], "label": label, "phase": phase},
            )

    after(s, push)
    return {"ok": True, "event": e.id}


async def close_stale(s: AsyncSession) -> int:
    rows = (
        await s.scalars(
            select(CameraEvent).where(
                CameraEvent.ended_at.is_(None), CameraEvent.started_at < now() - timedelta(seconds=STALE)
            )
        )
    ).all()
    for e in rows:
        e.ended_at = e.started_at + timedelta(seconds=STALE)
        d = await s.scalar(select(Device).join(Camera, Camera.device_id == Device.id).where(Camera.id == e.camera_id))
        cap = LABEL_CAP.get(e.label, e.label)
        if d is not None and (d.state or {}).get(cap):
            await devices.apply(s, d, {cap: False})
    return len(rows)


async def attach(s: AsyncSession, event_id: int, snapshot_id: Any = None, clip_id: Any = None) -> None:
    e = await s.get(CameraEvent, event_id)
    if e is None:
        return
    if snapshot_id is not None:
        e.snapshot_id = snapshot_id
    if clip_id is not None:
        e.clip_id = clip_id
    d = await s.scalar(select(Device).join(Camera, Camera.device_id == Device.id).where(Camera.id == e.camera_id))
    out = msgspec.to_builtins(ev_view(e))
    rooms = devices.rooms_of(d) if d else ["all"]
    after(s, lambda: realtime.emit("camera_event", out, rooms, durable=False))


async def rtc_check(s: AsyncSession, p: Principal, uri: str) -> str:
    """Разрешить запрос edge к службе видео. Возвращает заголовок авторизации для go2rtc."""
    u = urlsplit(uri or "")
    if u.path not in RTC_PATHS:
        raise ApplicationError("forbidden", 403)
    src = (parse_qs(u.query).get("src") or [""])[0]
    cid = rtc.camera_of(src)
    if not cid:
        raise ApplicationError("forbidden", 403)
    await _load(s, p, cid)
    return rtc.auth_header()
