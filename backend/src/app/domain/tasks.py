import sys
from typing import Any

from app.db.base import commit, session
from app.domain import cameras, devices, events, extensions, flows, scenes, system, zigbee
from app.lib import log
from app.lib.errors import ApplicationError, notice
from app.lib.kv import beat, kv
from app.lib.tasks import broker

if broker.is_worker_process:
    log.setup("worker")
elif any(a.endswith("scheduler") for a in sys.argv[:3]):
    log.setup("scheduler")
_log = log.get("tasks")


@broker.task(task_name="commands.timeout")
async def commands_timeout(id: str) -> None:
    async with session() as s:
        await devices.timeout(s, id)
        await commit(s)


@broker.task(task_name="flows.dispatch")
async def flows_dispatch(event: dict[str, Any]) -> None:
    async with session() as s:
        await flows.dispatch(s, event)
        await commit(s)


@broker.task(task_name="flows.resume")
async def flows_resume(run: str, node: str, port: int = 0, token: dict[str, Any] | None = None) -> None:
    async with session() as s:
        await flows.resume(s, run, node, port, token or {})
        await commit(s)


@broker.task(task_name="flows.wait_timeout")
async def flows_wait_timeout(run: str, node: str) -> None:
    async with session() as s:
        await flows.wait_timeout(s, run, node)
        await commit(s)


@broker.task(task_name="flows.queued")
async def flows_queued(flow: str) -> None:
    async with session() as s:
        await flows.queued(s, flow)
        await commit(s)


@broker.task(task_name="flows.reindex")
async def flows_reindex() -> None:
    async with session() as s:
        await flows.reindex(s)


@broker.task(task_name="flows.tick", schedule=[{"cron": "* * * * *"}])
async def flows_tick() -> None:
    await beat("worker", 150)
    if await events.wants("tick"):
        async with session() as s:
            await flows.dispatch(s, {"type": "tick"})
            await commit(s)


@broker.task(task_name="history.aggregate", schedule=[{"cron": "5 * * * *"}])
async def history_aggregate() -> None:
    async with session() as s:
        n = await devices.aggregate(s)
        await commit(s)
        _log.info("history_aggregated", rows=n)


@broker.task(task_name="history.purge", schedule=[{"cron": "30 2 * * *"}])
async def history_purge() -> None:
    async with session() as s:
        h = await events.home(s)
        n = await devices.purge(s, int(h.settings.get("historyDays", 10)))
        await commit(s)
        _log.info("history_purged", rows=n)


@broker.task(task_name="backups.daily", schedule=[{"cron": "30 1 * * *"}])
async def backups_daily() -> None:
    async with session() as s:
        h = await events.home(s)
        if h.settings.get("autoBackup", True):
            await system.backup_create(s, None, "scheduled")
            await commit(s)


@broker.task(task_name="backups.catchup", schedule=[{"cron": "50 * * * *"}])
async def backups_catchup() -> None:
    async with session() as s:
        if not await system.backup_overdue(s):
            return
        try:
            await system.backup_create(s, None, "scheduled")
        except ApplicationError as e:
            _log.info("backup_catchup_postponed", code=e.code)
            return
        await commit(s)
        _log.warning("backup_catchup")


@broker.task(task_name="backups.run")
async def backups_run(id: str, token: str = "") -> None:
    if not await system.once(token):
        _log.warning("backup_task_repeated", backup=id)
        return
    owner = f"backup:{id}"
    if not await system.acquire(owner):
        _log.error("backup_lock_busy", backup=id)
        async with session() as s:
            await system.backup_skipped(s, id)
            await commit(s)
        return
    try:
        async with session() as s:
            await system.backup_run(s, id)
            await commit(s)
    finally:
        await system.release(owner)


@broker.task(task_name="backups.restore")
async def backups_restore(path: str, actor: str = "system", token: str = "") -> None:
    if not await system.once(token):
        _log.warning("restore_task_repeated", path=path)
        return
    owner = f"restore:{token}"
    if not await system.acquire(owner):
        _log.error("restore_lock_busy", path=path)
        async with session() as s:
            await events.add(
                s, "backup.restore_failed", "crit", actor=actor, params={"error": "backup or restore in progress"}
            )
            await commit(s)
        return
    meta: dict[str, Any] = {}
    try:
        meta = await system.restore_run(path)
        ok, err = True, None
    except Exception as e:
        _log.error("restore_failed", path=path, error=str(e), exc_info=True)
        ok, err = False, str(e)[:300]
    finally:
        await system.release(owner)
    if ok:
        async with session() as s:
            await system.restored(s, path, meta)
            await commit(s)
        await kv().delete("ha:configs", "ha:hash", "z2m:names")
        await kv().publish("mqtt:index", "resync")
        async with session() as s:
            await flows.reindex(s)
    async with session() as s:
        await events.add(
            s,
            "backup.restored" if ok else "backup.restore_failed",
            "ok" if ok else "crit",
            actor=actor,
            params={"error": err},
        )
        await commit(s)


@broker.task(task_name="cameras.sync_driver")
async def cameras_sync_driver(driver: str) -> None:
    await cameras.sync_driver(driver)


@broker.task(task_name="zigbee.networkmap")
async def zigbee_networkmap() -> None:
    await zigbee.networkmap_run()


@broker.task(task_name="zigbee.ota")
async def zigbee_ota(address: str, device: str) -> None:
    async with session() as s:
        await zigbee.ota_run(s, address, device)
        await commit(s)


@broker.task(task_name="scenes.done")
async def scenes_done(
    group: str, scene: str, name: str, actor: str, total: int, failed: list[str], cause: int | None = None
) -> None:
    async with session() as s:
        await scenes.done(s, name, actor, total, failed, cause)
        await commit(s)


@broker.task(task_name="ext.push")
async def ext_push(type: str, level: str, params: dict[str, Any], force: bool = False) -> None:
    async with session() as s:
        h = await events.home(s)
        if not force and level not in h.settings.get("pushLevels", ["crit"]):
            return
        text = notice(type, h.settings.get("lang", "uk"), **params)
        await extensions.push(s, text, level)
        await commit(s)


@broker.task(task_name="zigbee.offline_alert")
async def zigbee_offline_alert() -> None:
    async with session() as s:
        await zigbee.offline_alert(s)
        await commit(s)


@broker.task(task_name="cameras.reprobe")
async def cameras_reprobe(camera: str, attempt: int = 0) -> None:
    await cameras.reprobe(camera, attempt)


@broker.task(task_name="cameras.patrol")
async def cameras_patrol(camera: str, presets: list[str], seconds: int, rounds: int) -> None:
    await cameras.patrol(camera, presets, seconds, rounds)
