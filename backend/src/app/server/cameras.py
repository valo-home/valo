import pathlib
import re
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

import anyio
from litestar import Request, Response, Router, delete, get, post
from litestar import patch as patch_route
from litestar.di import NamedDependency, Provide
from litestar.params import FromPath, FromQuery, JSONBody
from litestar.response import Stream
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import cameras, media
from app.domain.common import Principal, S
from app.lib.errors import ApplicationError
from app.server.base import authed, done, principal

Db = NamedDependency[AsyncSession]
P = NamedDependency[Principal]
CHUNK = 256 * 1024
_RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")
TYPES = {"photo": "image/jpeg", "video": "video/mp4"}


class ClipIn(S):
    seconds: int = 15


@get("/cameras")
async def cam_list(db_session: Db, p: P) -> list[cameras.CameraOut]:
    return await cameras.listing(db_session, p)


@get("/cameras/drivers")
async def cam_drivers(db_session: Db, p: P) -> list[cameras.DriverOut]:
    p.need("member")
    return await cameras.drivers(db_session)


@get("/cameras/rtc-auth")
async def cam_rtc_auth(request: Request, db_session: Db, p: P) -> Response:
    header = await cameras.rtc_check(db_session, p, request.headers.get("x-forwarded-uri", ""))
    return Response(b"", status_code=200, headers={"Authorization": header, "Cache-Control": "no-store"})


@post("/cameras/probe", status_code=200)
async def cam_probe(db_session: Db, p: P, data: JSONBody[cameras.ProbeIn]) -> dict[str, Any]:
    return await cameras.probe(db_session, p, data)


@post("/cameras", status_code=201)
async def cam_create(db_session: Db, p: P, data: JSONBody[cameras.CameraIn]) -> cameras.CameraOut:
    return await done(db_session, await cameras.create(db_session, p, data))


@get("/cameras/{camera_id:str}")
async def cam_one(db_session: Db, p: P, camera_id: FromPath[str]) -> cameras.CameraOut:
    return await cameras.one(db_session, p, camera_id)


@patch_route("/cameras/{camera_id:str}")
async def cam_update(
    db_session: Db, p: P, camera_id: FromPath[str], data: JSONBody[cameras.CameraPatch]
) -> cameras.CameraOut:
    return await done(db_session, await cameras.update(db_session, p, camera_id, data))


@delete("/cameras/{camera_id:str}", status_code=204)
async def cam_delete(db_session: Db, p: P, camera_id: FromPath[str], media: FromQuery[str] = "keep") -> None:
    await cameras.remove(db_session, p, camera_id, keep_media=media != "delete")
    await done(db_session)


@post("/cameras/{camera_id:str}/test", status_code=200)
async def cam_test(db_session: Db, p: P, camera_id: FromPath[str], data: JSONBody[cameras.TestIn]) -> dict[str, Any]:
    return await cameras.test(db_session, p, camera_id, data)


@get("/cameras/{camera_id:str}/settings")
async def cam_settings(db_session: Db, p: P, camera_id: FromPath[str]) -> dict[str, Any]:
    return await cameras.settings_get(db_session, p, camera_id)


@patch_route("/cameras/{camera_id:str}/settings")
async def cam_settings_set(
    db_session: Db, p: P, camera_id: FromPath[str], data: JSONBody[cameras.SettingsIn]
) -> dict[str, Any]:
    return await done(db_session, await cameras.settings_set(db_session, p, camera_id, data.values))


@post("/cameras/{camera_id:str}/action", status_code=200)
async def cam_action(
    db_session: Db, p: P, camera_id: FromPath[str], data: JSONBody[cameras.ActionIn]
) -> dict[str, Any]:
    return await done(db_session, await cameras.action(db_session, p, camera_id, data.action, data.params))


@get("/cameras/{camera_id:str}/diagnose")
async def cam_diagnose(db_session: Db, p: P, camera_id: FromPath[str]) -> dict[str, Any]:
    return await cameras.diagnose(db_session, p, camera_id)


@post("/cameras/{camera_id:str}/discover", status_code=200)
async def cam_discover(db_session: Db, p: P, camera_id: FromPath[str]) -> dict[str, Any]:
    return await done(db_session, await cameras.discover(db_session, p, camera_id))


@post("/cameras/{camera_id:str}/ptz", status_code=200)
async def cam_ptz(db_session: Db, p: P, camera_id: FromPath[str], data: JSONBody[dict[str, Any]]) -> dict[str, Any]:
    return await cameras.ptz(db_session, p, camera_id, data)


@post("/cameras/{camera_id:str}/presets", status_code=201)
async def cam_preset_add(
    db_session: Db, p: P, camera_id: FromPath[str], data: JSONBody[cameras.PresetIn]
) -> list[dict[str, Any]]:
    return await done(db_session, await cameras.preset_add(db_session, p, camera_id, data.name))


@patch_route("/cameras/{camera_id:str}/presets/{pid:str}")
async def cam_preset_edit(
    db_session: Db, p: P, camera_id: FromPath[str], pid: FromPath[str], data: JSONBody[cameras.PresetIn]
) -> list[dict[str, Any]]:
    return await done(db_session, await cameras.preset_edit(db_session, p, camera_id, pid, data.name))


@delete("/cameras/{camera_id:str}/presets/{pid:str}", status_code=200)
async def cam_preset_delete(db_session: Db, p: P, camera_id: FromPath[str], pid: FromPath[str]) -> list[dict[str, Any]]:
    return await done(db_session, await cameras.preset_edit(db_session, p, camera_id, pid, None, remove_=True))


@post("/cameras/{camera_id:str}/presets/{pid:str}/go", status_code=200)
async def cam_preset_go(db_session: Db, p: P, camera_id: FromPath[str], pid: FromPath[str]) -> dict[str, Any]:
    p.need("member")
    return await cameras.preset_go(db_session, p, camera_id, pid)


@delete("/cameras/{camera_id:str}/events/{event_id:int}", status_code=200)
async def cam_event_delete(db_session: Db, p: P, camera_id: FromPath[str], event_id: FromPath[int]) -> dict[str, int]:
    n = await cameras.event_remove(db_session, p, camera_id, event_id)
    await done(db_session)
    return {"deleted": n}


@get("/cameras/{camera_id:str}/preview")
async def cam_preview(db_session: Db, p: P, camera_id: FromPath[str], full: FromQuery[bool] = False) -> Response:
    data = await cameras.preview(db_session, p, camera_id, full)
    return Response(data, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=5"})


@post("/cameras/{camera_id:str}/snapshot", status_code=201)
async def cam_snapshot(db_session: Db, p: P, camera_id: FromPath[str]) -> media.MediaOut:
    return await done(db_session, await cameras.snapshot(db_session, p, camera_id))


@post("/cameras/{camera_id:str}/clip", status_code=202)
async def cam_clip(db_session: Db, p: P, camera_id: FromPath[str], data: JSONBody[ClipIn]) -> dict[str, Any]:
    p.need("member")
    return await done(db_session, await cameras.clip(db_session, p, camera_id, data.seconds, p.actor))


@get("/cameras/{camera_id:str}/events")
async def cam_events(
    db_session: Db,
    p: P,
    camera_id: FromPath[str],
    before: FromQuery[str] = "",
    label: FromQuery[str] = "",
    day: FromQuery[str] = "",
    limit: FromQuery[int] = 50,
) -> list[cameras.EventOut]:
    return await cameras.event_list(db_session, p, camera_id, before, label, limit, day)


@get("/media")
async def media_list(
    db_session: Db,
    p: P,
    camera: FromQuery[str] = "",
    kind: FromQuery[str] = "",
    day: FromQuery[str] = "",
    before: FromQuery[str] = "",
    limit: FromQuery[int] = 60,
) -> list[media.MediaOut]:
    return await media.listing(db_session, p, camera, kind, day, before, limit)


@get("/media/days")
async def media_days(db_session: Db, p: P, camera: FromQuery[str] = "") -> list[dict[str, Any]]:
    return await media.days(db_session, p, camera)


@post("/media/delete", status_code=200)
async def media_delete_many(db_session: Db, p: P, data: JSONBody[media.BulkIn]) -> dict[str, int]:
    return await done(db_session, await media.remove_many(db_session, p, data))


@patch_route("/media/{media_id:str}")
async def media_keep(db_session: Db, p: P, media_id: FromPath[str], data: JSONBody[media.KeepIn]) -> media.MediaOut:
    return await done(db_session, await media.set_keep(db_session, p, media_id, data.keep))


@get("/media/zip")
async def media_zip(db_session: Db, p: P, ids: FromQuery[str]) -> Stream:
    files = await media.bundle(db_session, p, [i for i in ids.split(",") if i])
    tmp = media.root() / ".valo-tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    target = tmp / f"zip-{uuid.uuid4().hex}.zip"
    await anyio.to_thread.run_sync(media.zip_to, files, target)
    size = target.stat().st_size

    async def body() -> AsyncIterator[bytes]:
        try:
            async for block in _chunks(target, 0, size):
                yield block
        finally:
            target.unlink(missing_ok=True)

    name = f"valo-media-{time.strftime('%Y%m%d-%H%M%S')}.zip"
    return Stream(
        body(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{name}"', "Content-Length": str(size)},
    )


@get("/media/storage")
async def media_storage(db_session: Db, p: P) -> dict[str, Any]:
    return await media.storage(db_session, p)


@patch_route("/media/storage")
async def media_configure(db_session: Db, p: P, data: JSONBody[media.StorageIn]) -> dict[str, Any]:
    return await done(db_session, await media.configure(db_session, p, data))


async def _chunks(f: pathlib.Path, start: int, length: int) -> AsyncIterator[bytes]:
    async with await anyio.open_file(f, "rb") as fh:
        await fh.seek(start)
        left = length
        while left > 0:
            block = await fh.read(min(CHUNK, left))
            if not block:
                break
            left -= len(block)
            yield block


@get("/media/{media_id:str}/file")
async def media_file(request: Request, db_session: Db, p: P, media_id: FromPath[str]) -> Stream:
    m, f = await media.get(db_session, p, media_id)
    size = f.stat().st_size
    kind = TYPES.get(m.kind, "application/octet-stream")
    headers = {"Accept-Ranges": "bytes", "Cache-Control": "private, max-age=86400"}
    if request.query_params.get("download"):
        headers["Content-Disposition"] = f'attachment; filename="{f.name}"'
    rng = _RANGE.match(request.headers.get("range", "").strip())
    if not rng or (not rng[1] and not rng[2]):
        return Stream(_chunks(f, 0, size), media_type=kind, headers={**headers, "Content-Length": str(size)})
    if rng[1]:
        start = int(rng[1])
        end = min(int(rng[2]), size - 1) if rng[2] else size - 1
    else:
        start, end = max(0, size - int(rng[2])), size - 1
    if start >= size or start > end:
        raise ApplicationError("range_invalid", 416)
    length = end - start + 1
    return Stream(
        _chunks(f, start, length),
        status_code=206,
        media_type=kind,
        headers={**headers, "Content-Range": f"bytes {start}-{end}/{size}", "Content-Length": str(length)},
    )


@delete("/media/{media_id:str}", status_code=204)
async def media_delete(db_session: Db, p: P, media_id: FromPath[str]) -> None:
    await media.remove(db_session, p, media_id)
    await done(db_session)


cams = Router(
    "/api/v1",
    dependencies={"p": Provide(principal)},
    guards=[authed],
    route_handlers=[
        cam_list,
        cam_drivers,
        cam_rtc_auth,
        cam_probe,
        cam_create,
        cam_one,
        cam_update,
        cam_delete,
        cam_test,
        cam_settings,
        cam_settings_set,
        cam_action,
        cam_diagnose,
        cam_discover,
        cam_ptz,
        cam_preset_add,
        cam_preset_edit,
        cam_preset_delete,
        cam_preset_go,
        cam_event_delete,
        cam_preview,
        cam_snapshot,
        cam_clip,
        cam_events,
        media_list,
        media_days,
        media_delete_many,
        media_zip,
        media_keep,
        media_storage,
        media_configure,
        media_file,
        media_delete,
    ],
)
