from typing import Any
from urllib.parse import unquote

from litestar import Request, Router, delete, get, post
from litestar import patch as patch_route
from litestar.di import NamedDependency, Provide
from litestar.params import FromPath, FromQuery, JSONBody
from litestar.response import File
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import auth, extensions, manual, mqttx, system, zigbee
from app.domain.common import Principal, S
from app.lib.errors import ApplicationError
from app.server.base import authed, done, principal

Db = NamedDependency[AsyncSession]
P = NamedDependency[Principal]


class JoinIn(S):
    time: int = 254
    via: str | None = None


class ChannelIn(S):
    channel: int


@get("/zigbee")
async def zb_info(db_session: Db) -> dict[str, Any]:
    return await zigbee.info(db_session)


@get("/zigbee/health")
async def zb_health(db_session: Db) -> list[dict[str, Any]]:
    return await zigbee.health(db_session)


@post("/zigbee/permit-join", status_code=200)
async def zb_join(db_session: Db, p: P, data: JSONBody[JoinIn]) -> dict[str, Any]:
    return await done(db_session, await zigbee.permit_join(db_session, p, data.time, data.via))


@post("/zigbee/networkmap", status_code=202)
async def zb_map_start(p: P) -> None:
    await zigbee.networkmap_start(p)


@get("/zigbee/networkmap")
async def zb_map() -> dict[str, Any]:
    return await zigbee.networkmap()


@post("/zigbee/devices/{device_id:str}/ota-check", status_code=200)
async def zb_ota_check(db_session: Db, p: P, device_id: FromPath[str]) -> Any:
    return await done(db_session, await zigbee.ota_check(db_session, p, device_id))


@post("/zigbee/devices/{device_id:str}/ota-update", status_code=202)
async def zb_ota(db_session: Db, p: P, device_id: FromPath[str]) -> None:
    await zigbee.ota_update(db_session, p, device_id)
    await done(db_session)


@post("/zigbee/devices/{device_id:str}/{action:str}", status_code=200)
async def zb_action(db_session: Db, p: P, device_id: FromPath[str], action: FromPath[str]) -> Any:
    return await done(db_session, await zigbee.device_action(db_session, p, device_id, action))


@post("/zigbee/channel", status_code=200)
async def zb_channel(db_session: Db, p: P, data: JSONBody[ChannelIn]) -> dict[str, Any]:
    return await done(db_session, await zigbee.set_channel(db_session, p, data.channel))


@get("/mqtt")
async def mq_info() -> dict[str, Any]:
    return await mqttx.broker()


@get("/mqtt/topics")
async def mq_topics(p: P) -> list[dict[str, Any]]:
    p.need("admin")
    return await mqttx.topics()


@get("/mqtt/topic")
async def mq_topic(p: P, t: FromQuery[str]) -> dict[str, Any]:
    p.need("admin")
    return await mqttx.topic(t)


@get("/mqtt/recent")
async def mq_recent(p: P, limit: FromQuery[int] = 100) -> list[list[Any]]:
    p.need("admin")
    return await mqttx.recent(min(limit, 200))


@post("/mqtt/publish", status_code=204)
async def mq_publish(db_session: Db, p: P, data: JSONBody[mqttx.PublishIn]) -> None:
    await mqttx.publish(db_session, p, data)
    await done(db_session)


@get("/mqtt/discovery")
async def mq_discovery(db_session: Db) -> list[dict[str, Any]]:
    return await mqttx.discovery(db_session)


@delete("/mqtt/discovery")
async def mq_drop(db_session: Db, p: P, t: FromQuery[str]) -> None:
    await mqttx.drop_config(db_session, p, t)
    await done(db_session)


@get("/mqtt/clients")
async def mq_clients(p: P) -> dict[str, Any]:
    p.need("admin")
    return await mqttx.clients()


@post("/mqtt/accounts", status_code=200)
async def mq_account(db_session: Db, p: P, data: JSONBody[mqttx.AccountIn]) -> dict[str, Any]:
    return await done(db_session, await mqttx.account(db_session, p, data.device_id))


@get("/extensions")
async def ext_list(db_session: Db) -> list[extensions.ExtOut]:
    return await extensions.listing(db_session)


@get("/extensions/catalog")
async def ext_catalog(db_session: Db) -> list[dict[str, Any]]:
    return await extensions.catalog(db_session)


@get("/extensions/contributions")
async def ext_contrib(db_session: Db) -> dict[str, Any]:
    return await extensions.contributions(db_session)


@get("/extensions/{ext_id:str}/docs")
async def ext_docs(ext_id: FromPath[str], lang: FromQuery[str] = "uk") -> dict[str, Any]:
    return extensions.docs(ext_id, lang[:5])


@get("/help")
async def help_index(lang: FromQuery[str] = "uk", q: FromQuery[str] = "") -> dict[str, Any]:
    if q.strip():
        return {"hits": manual.search(q[:120], lang[:5])}
    return manual.index(lang[:5])


@get("/help/{slug:str}")
async def help_page(slug: FromPath[str], lang: FromQuery[str] = "uk") -> dict[str, Any]:
    return manual.page(slug, lang[:5])


@get("/extensions/{ext_id:str}")
async def ext_one(db_session: Db, ext_id: FromPath[str]) -> extensions.ExtOut:
    return await extensions.one(db_session, ext_id)


@post("/extensions/{ext_id:str}/install", status_code=202)
async def ext_install(
    db_session: Db, p: P, ext_id: FromPath[str], data: JSONBody[extensions.InstallIn]
) -> extensions.ExtOut:
    return await done(db_session, await extensions.install(db_session, p, ext_id, data))


@post("/extensions/{ext_id:str}/{op:str}", status_code=202)
async def ext_op(db_session: Db, p: P, ext_id: FromPath[str], op: FromPath[str], request: Request) -> extensions.ExtOut:
    if op == "update":
        try:
            body = await request.json()
        except ValueError:
            body = None
        grants = body.get("grants") if isinstance(body, dict) else None
        return await done(db_session, await extensions.update(db_session, p, ext_id, grants))
    fn = {"toggle": extensions.toggle, "restart": extensions.restart}.get(op)
    if fn is None:
        raise ApplicationError("not_found", 404)
    return await done(db_session, await fn(db_session, p, ext_id))


@delete("/extensions/{ext_id:str}", status_code=202)
async def ext_remove(db_session: Db, p: P, ext_id: FromPath[str]) -> None:
    await extensions.remove(db_session, p, ext_id)
    await done(db_session)


@patch_route("/extensions/{ext_id:str}/settings")
async def ext_settings(
    db_session: Db, p: P, ext_id: FromPath[str], data: JSONBody[extensions.SettingsIn]
) -> extensions.ExtOut:
    return await done(db_session, await extensions.configure(db_session, p, ext_id, data))


@get("/extensions/{ext_id:str}/logs")
async def ext_logs(p: P, ext_id: FromPath[str]) -> list[str]:
    p.need("admin")
    return await extensions.logs(ext_id)


@get("/extensions/{ext_id:str}/ui/{path:path}")
async def ext_ui(db_session: Db, ext_id: FromPath[str], path: FromPath[str]) -> File:
    f = extensions.ui_file(await extensions.get(db_session, ext_id), path.lstrip("/"))
    return File(
        path=f,
        content_disposition_type="inline",
        headers={"Content-Security-Policy": "sandbox allow-scripts", "X-Content-Type-Options": "nosniff"},
    )


@post("/extensions/{ext_id:str}/page/{method:str}", status_code=200)
async def ext_page(
    db_session: Db, p: P, ext_id: FromPath[str], method: FromPath[str], data: JSONBody[dict[str, Any]]
) -> dict[str, Any]:
    p.need("member" if data.get("action") else "guest")
    return await extensions.rpc(db_session, ext_id, f"page.{method}", {**data, "role": p.role})


@get("/system")
async def sys_info(db_session: Db) -> dict[str, Any]:
    return await system.info(db_session)


@get("/system/resources")
async def sys_resources(db_session: Db, p: P) -> dict[str, Any]:
    p.need("admin")
    return await system.resources(db_session)


@get("/system/update")
async def sys_update(p: P) -> dict[str, Any]:
    p.need("admin")
    return await system.update_check()


@get("/system/backups")
async def backups(db_session: Db, p: P) -> list[system.BackupOut]:
    p.need("admin")
    return await system.backups(db_session)


@post("/system/backups", status_code=202)
async def backup_create(db_session: Db, p: P) -> system.BackupOut:
    return await done(db_session, await system.backup_create(db_session, p))


@get("/system/backups/{backup_id:str}/download")
async def backup_download(db_session: Db, p: P, backup_id: FromPath[str]) -> File:
    f = await system.backup_file(db_session, p, backup_id)
    return File(path=f, filename=f.name, media_type="application/gzip")


@post("/system/backups/{backup_id:str}/restore", status_code=202)
async def backup_restore(db_session: Db, p: P, backup_id: FromPath[str]) -> None:
    await system.restore(db_session, p, backup_id)
    await done(db_session)


@post("/system/backups/upload", status_code=201, request_max_body_size=system.UPLOAD_LIMIT)
async def backup_upload(db_session: Db, p: P, request: Request) -> system.BackupOut:
    data = await request.body()
    name = unquote(request.headers.get("x-filename", "backup.tar.gz"))
    return await done(db_session, await system.backup_upload(db_session, p, data, name))


@delete("/system/backups/{backup_id:str}")
async def backup_delete(db_session: Db, p: P, backup_id: FromPath[str]) -> None:
    await system.backup_delete(db_session, p, backup_id)
    await done(db_session)


@get("/system/errors")
async def sys_errors(p: P) -> dict[str, Any]:
    return await system.errors(p)


@post("/system/errors/seen", status_code=204)
async def sys_errors_seen(p: P) -> None:
    await system.errors_seen(p)


@delete("/system/errors")
async def sys_errors_clear(p: P) -> None:
    await system.errors_clear(p)


@post("/system/errors/report", status_code=204)
async def sys_error_report(p: P, data: JSONBody[system.ErrorReportIn]) -> None:
    await system.error_report(p, data)


@get("/users")
async def users(db_session: Db, p: P) -> list[auth.UserOut]:
    return await auth.users(db_session, p)


@post("/users")
async def user_create(db_session: Db, p: P, data: JSONBody[auth.UserIn]) -> auth.UserOut:
    return await done(db_session, await auth.create_user(db_session, p, data))


@patch_route("/users/{user_id:str}")
async def user_update(db_session: Db, p: P, user_id: FromPath[str], data: JSONBody[auth.UserPatch]) -> auth.UserOut:
    return await done(db_session, await auth.update_user(db_session, p, user_id, data))


@delete("/users/{user_id:str}")
async def user_delete(db_session: Db, p: P, user_id: FromPath[str]) -> None:
    await auth.delete_user(db_session, p, user_id)
    await done(db_session)


@get("/tokens")
async def tokens(db_session: Db, p: P) -> list[auth.TokenOut]:
    return await auth.tokens(db_session, p)


@post("/tokens")
async def token_create(db_session: Db, p: P, data: JSONBody[auth.TokenIn]) -> dict[str, Any]:
    return await done(db_session, await auth.create_token(db_session, p, data))


@delete("/tokens/{token_id:str}")
async def token_delete(db_session: Db, p: P, token_id: FromPath[str]) -> None:
    await auth.delete_token(db_session, p, token_id)
    await done(db_session)


admin = Router(
    "/api/v1",
    dependencies={"p": Provide(principal)},
    guards=[authed],
    route_handlers=[
        zb_info,
        zb_health,
        zb_join,
        zb_map_start,
        zb_map,
        zb_ota_check,
        zb_ota,
        zb_action,
        zb_channel,
        mq_info,
        mq_topics,
        mq_topic,
        mq_recent,
        mq_publish,
        mq_discovery,
        mq_drop,
        mq_clients,
        mq_account,
        ext_list,
        ext_catalog,
        ext_contrib,
        ext_one,
        ext_docs,
        help_index,
        help_page,
        ext_install,
        ext_op,
        ext_remove,
        ext_settings,
        ext_logs,
        ext_ui,
        ext_page,
        sys_info,
        sys_resources,
        sys_update,
        backups,
        backup_create,
        backup_download,
        backup_restore,
        backup_delete,
        backup_upload,
        sys_errors,
        sys_errors_seen,
        sys_errors_clear,
        sys_error_report,
        users,
        user_create,
        user_update,
        user_delete,
        tokens,
        token_create,
        token_delete,
    ],
)
