import json
from typing import Any

from litestar import Request, Router, delete, get, post
from litestar import patch as patch_route
from litestar.di import NamedDependency, Provide
from litestar.params import FromPath, FromQuery, JSONBody
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Flow
from app.domain import auth, coordinator, devices, events, extensions, flows, home, scenes
from app.domain.blocks import BlockDef
from app.domain.common import Principal
from app.lib.errors import ApplicationError
from app.lib.kv import kv
from app.lib.settings import env, environment, settings
from app.server.base import authed, client_ip, done, principal

Db = NamedDependency[AsyncSession]
P = NamedDependency[Principal]


@post("/auth/login", status_code=200)
async def login(request: Request, db_session: Db, data: JSONBody[auth.LoginIn]) -> auth.Session:
    return await done(db_session, await auth.login(db_session, data, client_ip(request)))


@get("/setup")
async def setup_status(db_session: Db) -> dict[str, Any]:
    return await home.setup_status(db_session)


@post("/setup", status_code=200)
async def setup(db_session: Db, data: JSONBody[home.SetupIn]) -> auth.Session:
    return await done(db_session, await home.setup(db_session, data))


@get("/setup/adapters")
async def setup_adapters(db_session: Db) -> dict[str, Any]:
    await home.setup_open(db_session)
    return coordinator.status()


@post("/setup/adapter", status_code=200)
async def setup_adapter(db_session: Db, data: JSONBody[coordinator.AdapterIn]) -> dict[str, Any]:
    await home.setup_open(db_session)
    return coordinator.choose(data)


@get("/health")
async def health() -> dict[str, bool]:
    return {"ok": True}


public = Router("/api/v1", route_handlers=[login, setup_status, setup, setup_adapters, setup_adapter, health])


@get("/zigbee/adapter")
async def zigbee_adapter(p: P) -> dict[str, Any]:
    p.need("admin")
    return coordinator.status()


@post("/zigbee/adapter", status_code=200)
async def zigbee_adapter_set(db_session: Db, p: P, data: JSONBody[coordinator.AdapterIn]) -> dict[str, Any]:
    p.need("admin")
    res = coordinator.choose(data)
    await events.add(db_session, "zigbee.adapter", actor=p.actor, params={"path": data.path, "type": data.type})
    await done(db_session)
    return res


@get("/auth/me")
async def me(p: P) -> P:
    return p


@post("/auth/ws-ticket", status_code=200)
async def ws_ticket(p: P) -> dict[str, str]:
    return {"ticket": auth.ws_ticket(p), "url": env("WS_PUBLIC_URL")}


@get("/overview")
async def overview(db_session: Db, p: P) -> dict[str, Any]:
    s = db_session
    return {
        "home": await home.get_home(s),
        "rooms": await home.rooms(s),
        "devices": await devices.listing(s, p),
        "scenes": await scenes.listing(s),
        "flows": await flows.listing(s),
        "notifications": await events.active(s),
        "events": await events.listing(s, p, limit=40),
        "summary": await devices.summary(s, p),
        "contrib": await extensions.contributions(s),
        "runs": await flows.stats(s),
        "env": environment(),
    }


@get("/home")
async def get_home(db_session: Db) -> home.HomeOut:
    return await home.get_home(db_session)


@patch_route("/home")
async def update_home(db_session: Db, p: P, data: JSONBody[home.HomePatch]) -> home.HomeOut:
    return await done(db_session, await home.update_home(db_session, p, data))


@get("/rooms")
async def rooms(db_session: Db) -> list[home.RoomOut]:
    return await home.rooms(db_session)


@post("/rooms")
async def create_room(db_session: Db, p: P, data: JSONBody[home.RoomIn]) -> home.RoomOut:
    return await done(db_session, await home.create_room(db_session, p, data))


@patch_route("/rooms/{room_id:str}")
async def update_room(db_session: Db, p: P, room_id: FromPath[str], data: JSONBody[home.RoomPatch]) -> home.RoomOut:
    return await done(db_session, await home.update_room(db_session, p, room_id, data))


@delete("/rooms/{room_id:str}")
async def delete_room(db_session: Db, p: P, room_id: FromPath[str]) -> None:
    await home.delete_room(db_session, p, room_id)
    await done(db_session)


@get("/devices")
async def list_devices(
    db_session: Db, p: P, room: FromQuery[str] = "", source: FromQuery[str] = "", q: FromQuery[str] = ""
) -> list[devices.DeviceOut]:
    return await devices.listing(db_session, p, room, source, q)


@post("/devices/mapping")
async def mapping(db_session: Db, p: P, data: JSONBody[devices.MappingIn]) -> devices.DeviceOut:
    return await done(db_session, await devices.mapped(db_session, p, data))


@get("/devices/{device_id:str}")
async def get_device(db_session: Db, p: P, device_id: FromPath[str]) -> devices.DeviceOut:
    d = await devices.get(db_session, device_id)
    p.need_room(d.room_id)
    return devices.view(d)


@patch_route("/devices/{device_id:str}")
async def update_device(
    db_session: Db, p: P, device_id: FromPath[str], data: JSONBody[devices.DevicePatch]
) -> devices.DeviceOut:
    return await done(db_session, await devices.update(db_session, p, device_id, data))


@delete("/devices/{device_id:str}")
async def delete_device(db_session: Db, p: P, device_id: FromPath[str], force: FromQuery[bool] = False) -> None:
    await devices.remove(db_session, p, device_id, force)
    await done(db_session)


@post("/devices/{device_id:str}/command", status_code=202)
async def command(
    db_session: Db, p: P, device_id: FromPath[str], data: JSONBody[devices.CommandIn]
) -> devices.CommandOut:
    return await done(db_session, await devices.command(db_session, p, device_id, data.values))


@get("/devices/{device_id:str}/history")
async def history(
    db_session: Db, p: P, device_id: FromPath[str], cap: FromQuery[str], hours: FromQuery[float] = 24
) -> dict[str, Any]:
    p.need_room((await devices.get(db_session, device_id)).room_id)
    return await devices.history(db_session, device_id, cap, min(hours, 24 * 400))


@get("/devices/{device_id:str}/commands")
async def device_commands(
    db_session: Db,
    p: P,
    device_id: FromPath[str],
    before: FromQuery[str | None] = None,
    limit: FromQuery[int] = 30,
) -> list[devices.CommandOut]:
    p.need_room((await devices.get(db_session, device_id)).room_id)
    return await devices.commands(db_session, device_id, max(1, min(limit, 200)), before)


@get("/devices/{device_id:str}/events")
async def device_events(
    db_session: Db, p: P, device_id: FromPath[str], before: FromQuery[int | None] = None, limit: FromQuery[int] = 60
) -> list[events.EventOut]:
    p.need_room((await devices.get(db_session, device_id)).room_id)
    return await events.listing(db_session, p, device=device_id, before=before, limit=max(1, min(limit, 200)))


@get("/devices/{device_id:str}/flows")
async def device_flows(db_session: Db, device_id: FromPath[str]) -> list[dict[str, Any]]:
    res = []
    for f in (await db_session.scalars(select(Flow))).all():
        nodes = [n for n in f.graph.get("nodes", []) if (n.get("params") or {}).get("device") == device_id]
        if nodes:
            res.append(
                {
                    "id": f.id,
                    "name": f.name,
                    "enabled": f.enabled,
                    "lastResult": f.last_result,
                    "nodes": [n.get("block") for n in nodes],
                }
            )
    return res


@get("/devices/{device_id:str}/topics")
async def device_topics(db_session: Db, device_id: FromPath[str]) -> list[dict[str, Any]]:
    d = await devices.get(db_session, device_id)
    prefix = {
        "zigbee": [f"{settings.z2m_topic}/{d.address}"],
        "mqtt": [f"hub/v1/dev/{d.address}/"],
        "ext": [f"hub/v1/ext/{d.ext_id}/dev/{d.address}/"],
        "ha": [
            *d.attrs.get("configs", []),
            *{c.get("st") for c in (d.attrs.get("conv") or {}).values() if c.get("st")},
        ],
        "map": [r.get("topic") for r in d.attrs.get("map") or []],
    }.get(d.source, [])
    rows = []
    for t, raw in (await kv().hgetall("mqtt:topics")).items():
        if any(
            t == x or t.startswith(x.rstrip("/") + "/") or (x.endswith("/") and t.startswith(x)) for x in prefix if x
        ):
            rows.append({"t": t, **json.loads(raw)})
    return sorted(rows, key=lambda r: r["t"])


@get("/scenes")
async def list_scenes(db_session: Db) -> list[scenes.SceneOut]:
    return await scenes.listing(db_session)


@post("/scenes")
async def create_scene(db_session: Db, p: P, data: JSONBody[scenes.SceneIn]) -> scenes.SceneOut:
    return await done(db_session, await scenes.create(db_session, p, data))


@patch_route("/scenes/{scene_id:str}")
async def update_scene(
    db_session: Db, p: P, scene_id: FromPath[str], data: JSONBody[scenes.ScenePatch]
) -> scenes.SceneOut:
    return await done(db_session, await scenes.update(db_session, p, scene_id, data))


@delete("/scenes/{scene_id:str}")
async def delete_scene(db_session: Db, p: P, scene_id: FromPath[str]) -> None:
    await scenes.remove(db_session, p, scene_id)
    await done(db_session)


@post("/scenes/{scene_id:str}/apply", status_code=202)
async def apply_scene(db_session: Db, p: P, scene_id: FromPath[str]) -> dict[str, Any]:
    return await done(db_session, await scenes.apply(db_session, p, scene_id))


@post("/scenes/{scene_id:str}/capture", status_code=200)
async def capture_scene(db_session: Db, p: P, scene_id: FromPath[str]) -> scenes.SceneOut:
    return await done(db_session, await scenes.capture(db_session, p, scene_id))


@get("/dashboards")
async def list_dashboards(db_session: Db) -> list[home.DashOut]:
    return await home.dashboards(db_session)


@post("/dashboards")
async def create_dashboard(db_session: Db, p: P, data: JSONBody[home.DashIn]) -> home.DashOut:
    return await done(db_session, await home.create_dashboard(db_session, p, data))


@patch_route("/dashboards/{dash_id:str}")
async def update_dashboard(
    db_session: Db, p: P, dash_id: FromPath[str], data: JSONBody[home.DashPatch]
) -> home.DashOut:
    return await done(db_session, await home.update_dashboard(db_session, p, dash_id, data))


@delete("/dashboards/{dash_id:str}")
async def delete_dashboard(db_session: Db, p: P, dash_id: FromPath[str]) -> None:
    await home.delete_dashboard(db_session, p, dash_id)
    await done(db_session)


@get("/events")
async def list_events(
    db_session: Db,
    p: P,
    kind: FromQuery[str] = "",
    level: FromQuery[str] = "",
    q: FromQuery[str] = "",
    device: FromQuery[str] = "",
    flow: FromQuery[str] = "",
    before: FromQuery[int | None] = None,
    limit: FromQuery[int] = 100,
) -> list[events.EventOut]:
    return await events.listing(db_session, p, kind, level, q, device, flow, before, limit)


@get("/events/{event_id:int}/chain")
async def event_chain(db_session: Db, event_id: FromPath[int]) -> list[events.EventOut]:
    return await events.chain(db_session, event_id)


@get("/notifications")
async def notifications(db_session: Db, history: FromQuery[bool] = False) -> list[events.NotificationOut]:
    return await events.active(db_session, history)


@get("/notifications/{nid:int}")
async def notification(db_session: Db, p: P, nid: FromPath[int]) -> events.NotificationDetail:
    return await events.notification(db_session, p, nid)


@post("/notifications/{nid:int}/dismiss", status_code=204)
async def dismiss(db_session: Db, nid: FromPath[int]) -> None:
    await events.dismiss(db_session, nid)
    await done(db_session)


@get("/blocks")
async def blocks(db_session: Db) -> list[BlockDef]:
    return list((await flows.registry(db_session)).values())


@get("/flows")
async def list_flows(db_session: Db) -> list[flows.FlowOut]:
    return await flows.listing(db_session)


@get("/flows/templates")
async def templates(db_session: Db) -> list[dict[str, Any]]:
    return [*flows.TEMPLATES, *await extensions.templates(db_session)]


@post("/flows")
async def create_flow(db_session: Db, p: P, data: JSONBody[flows.FlowIn]) -> flows.FlowOut:
    return await done(db_session, await flows.create(db_session, p, data))


@get("/flows/{flow_id:str}")
async def get_flow(db_session: Db, flow_id: FromPath[str]) -> flows.FlowOut:
    return await flows.one(db_session, flow_id)


@patch_route("/flows/{flow_id:str}")
async def update_flow(db_session: Db, p: P, flow_id: FromPath[str], data: JSONBody[flows.FlowPatch]) -> flows.FlowOut:
    return await done(db_session, await flows.update(db_session, p, flow_id, data))


@delete("/flows/{flow_id:str}")
async def delete_flow(db_session: Db, p: P, flow_id: FromPath[str]) -> None:
    await flows.remove(db_session, p, flow_id)
    await done(db_session)


@get("/flows/{flow_id:str}/versions")
async def flow_versions(db_session: Db, flow_id: FromPath[str]) -> list[flows.VersionOut]:
    return await flows.versions(db_session, flow_id)


@post("/flows/{flow_id:str}/versions/{version:int}/restore", status_code=200)
async def flow_restore(db_session: Db, p: P, flow_id: FromPath[str], version: FromPath[int]) -> flows.FlowOut:
    return await done(db_session, await flows.restore(db_session, p, flow_id, version))


@get("/flows/{flow_id:str}/runs")
async def flow_runs(
    db_session: Db, p: P, flow_id: FromPath[str], before: FromQuery[str | None] = None, limit: FromQuery[int] = 20
) -> list[flows.RunOut]:
    if p.rooms:
        raise ApplicationError("forbidden", 403)
    await flows.get(db_session, flow_id)
    return await flows.runs(db_session, flow_id, max(1, min(limit, 200)), before)


@post("/flows/{flow_id:str}/test", status_code=200)
async def flow_test(db_session: Db, p: P, flow_id: FromPath[str], data: JSONBody[flows.TestIn]) -> dict[str, Any]:
    res = await flows.test(db_session, p, flow_id, data)
    await db_session.rollback()
    return res


@post("/flows/{flow_id:str}/run", status_code=200)
async def flow_run(db_session: Db, p: P, flow_id: FromPath[str]) -> dict[str, Any]:
    return await done(db_session, await flows.manual(db_session, p, flow_id))


core = Router(
    "/api/v1",
    dependencies={"p": Provide(principal)},
    guards=[authed],
    route_handlers=[
        zigbee_adapter,
        zigbee_adapter_set,
        me,
        ws_ticket,
        overview,
        get_home,
        update_home,
        rooms,
        create_room,
        update_room,
        delete_room,
        list_devices,
        mapping,
        get_device,
        update_device,
        delete_device,
        command,
        history,
        device_commands,
        device_events,
        device_flows,
        device_topics,
        list_scenes,
        create_scene,
        update_scene,
        delete_scene,
        apply_scene,
        capture_scene,
        list_dashboards,
        create_dashboard,
        update_dashboard,
        delete_dashboard,
        list_events,
        event_chain,
        notifications,
        notification,
        dismiss,
        blocks,
        list_flows,
        templates,
        create_flow,
        get_flow,
        update_flow,
        delete_flow,
        flow_versions,
        flow_restore,
        flow_runs,
        flow_test,
        flow_run,
    ],
)
