import asyncio
import json
import os
import pathlib
import shutil
import signal
import sys
import time
from typing import Any

from sqlalchemy import select

from app.db.base import commit, session
from app.db.models import Extension
from app.domain import extensions, mqttx, zigbee
from app.lib import errlog, log, realtime, tasks
from app.lib.errors import ApplicationError
from app.lib.kv import beat, kv
from app.lib.loops import forever
from app.lib.settings import env, env_int, settings

_log = log.get("ext")
PYTHON = env("EXT_PYTHON", sys.executable)
READY_TIMEOUT = 25
MAX_RESTARTS = 5
MEM_LIMIT = env_int("EXT_MEM_LIMIT", 256)
CPU_LIMIT = env_int("EXT_CPU_LIMIT", 80)
CPU_SAMPLES = 6
NICE = 10


def limits(m: dict[str, Any]) -> tuple[int, int]:
    rt = m.get("runtime") or {}
    mem = int(rt.get("memory") or MEM_LIMIT)
    cpu = int(rt.get("cpu") or CPU_LIMIT)
    return max(32, min(mem, MEM_LIMIT * 4)), max(5, min(cpu, 100))


def over(stats: dict[str, Any], mem: int, cpu: int, hot: int) -> tuple[str | None, int]:
    if stats.get("mem", 0) > mem:
        return f"memory limit {mem} MB exceeded ({stats['mem']} MB)", 0
    hot = hot + 1 if stats.get("cpu", 0) > cpu else 0
    if hot >= CPU_SAMPLES:
        return f"cpu limit {cpu}% exceeded for {CPU_SAMPLES * 5} s ({stats['cpu']}%)", 0
    return None, hot


class Proc:
    def __init__(self, ext_id: str, version: str, path: pathlib.Path, proc: asyncio.subprocess.Process) -> None:
        self.id, self.version, self.path, self.proc = ext_id, version, path, proc
        self.started, self.stopping, self.cpu = time.time(), False, (0.0, time.time())
        self.mtime = _mtime(path)
        self.limits = limits(json.loads((path / "manifest.json").read_text("utf-8")))
        self.hot = 0
        self.reason: str | None = None


procs: dict[str, Proc] = {}
crashes: dict[str, list[float]] = {}
busy: set[str] = set()
_bg: set[asyncio.Task] = set()


def bg(coro) -> None:
    t = asyncio.create_task(coro)
    _bg.add(t)
    t.add_done_callback(_bg.discard)


def _mtime(path: pathlib.Path) -> float:
    try:
        return max((f.stat().st_mtime for f in path.rglob("*") if f.suffix in (".py", ".json")), default=0.0)
    except OSError:
        return 0.0


async def set_status(
    ext_id: str, state: str, pid: int | None = None, error: str | None = None, version: str | None = None
) -> None:
    async with session() as s:
        await extensions.status(s, ext_id, state, pid, error, version)
        await commit(s)


async def _pipe(p: Proc) -> None:
    assert p.proc.stdout is not None
    async for line in p.proc.stdout:
        text = line.decode(errors="replace").rstrip()
        if text:
            await kv().lpush(f"ext:log:{p.id}", text[:2000])
            await kv().ltrim(f"ext:log:{p.id}", 0, 499)
            await realtime.emit("ext_log", {"ext": p.id, "line": text[:2000]}, [f"extlog:{p.id}"], durable=False)
            item = errlog.ext_line(p.id, text)
            if item:
                await errlog.astore(item)
    code = await p.proc.wait()
    if procs.get(p.id) is p and not p.stopping:
        await _crashed(p, code)


async def _crashed(p: Proc, code: int) -> None:
    procs.pop(p.id, None)
    now = time.time()
    hist = [t for t in crashes.get(p.id, []) if now - t < 600] + [now]
    crashes[p.id] = hist
    tail = list(reversed(await kv().lrange(f"ext:log:{p.id}", 0, 4)))
    _log.warning("ext_exited", ext=p.id, code=code, crashes=len(hist), reason=p.reason)
    await set_status(p.id, "error", error=p.reason or f"exit {code}: " + " | ".join(tail)[-400:])
    if len(hist) < MAX_RESTARTS:
        await asyncio.sleep(min(2 ** len(hist), 30))
        async with session() as s:
            x = await s.get(Extension, p.id)
            if x and x.enabled and x.id not in procs:
                await start(x)


def _source(x: Extension, version: str | None = None) -> pathlib.Path | None:
    found = extensions.source_for(x.id, version or x.version)
    return found[0] if found else None


def _dest(x: Extension, version: str | None = None) -> pathlib.Path:
    if x.trust == "local" and (src := _source(x, version)):
        return src
    return extensions.EXT_DIR / x.id / (version or x.version)


async def _prepare(x: Extension, version: str) -> pathlib.Path:
    src = _source(x, version)
    if src is None:
        raise ApplicationError("ext_not_found", 404)
    dest = _dest(x, version)
    if dest != src:
        await asyncio.to_thread(shutil.copytree, src, dest, dirs_exist_ok=True)
    m = json.loads((dest / "manifest.json").read_text("utf-8"))
    req = m.get("requires") or []
    if req:
        venv = dest / ".venv"
        await _exec("uv", "venv", str(venv))
        await _exec("uv", "pip", "install", "--python", str(venv / "bin" / "python"), *req)
    return dest


async def _exec(*cmd: str) -> None:
    p = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    out, _ = await p.communicate()
    if p.returncode:
        raise RuntimeError(f"{cmd[0]} {cmd[1]}: {out.decode(errors='replace')[-300:]}")


async def spawn(x: Extension, path: pathlib.Path, version: str) -> Proc:
    m = json.loads((path / "manifest.json").read_text("utf-8"))
    cred = await kv().get(f"ext:cred:{x.id}")
    if cred:
        user, pw = json.loads(cred)
    else:
        user, pw = await mqttx.ext_account(x.id, x.grants)
        await kv().set(f"ext:cred:{x.id}", json.dumps([user, pw]))
    data = extensions.EXT_DIR / x.id / "data"
    data.mkdir(parents=True, exist_ok=True)
    py = str(path / ".venv" / "bin" / "python") if (path / ".venv").exists() else PYTHON
    envs = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": os.pathsep.join(filter(None, [str(path), os.environ.get("EXT_SDK_PATH", "")])),
        "PYTHONUNBUFFERED": "1",
        "VALO_EXT_ID": x.id,
        "VALO_EXT_VERSION": version,
        "VALO_EXT_DIR": str(path),
        "VALO_EXT_DATA": str(data),
        "VALO_EXT_SETTINGS": json.dumps(extensions.plain_settings(x)),
        "VALO_MQTT_HOST": settings.mqtt_host,
        "VALO_MQTT_PORT": str(settings.mqtt_port),
        "VALO_MQTT_USER": user,
        "VALO_MQTT_PASSWORD": pw,
        "VALO_DEMO": env("VALO_DEMO"),
    }
    await kv().delete(f"ext:ready:{x.id}")
    proc = await asyncio.create_subprocess_exec(
        "nice",
        "-n",
        str(NICE),
        py,
        "-m",
        m["module"],
        cwd=str(path),
        env=envs,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        start_new_session=True,
    )
    p = Proc(x.id, version, path, proc)
    bg(_pipe(p))
    _log.info("ext_spawned", ext=x.id, version=version, pid=proc.pid)
    return p


async def ready(p: Proc) -> bool:
    end = time.time() + READY_TIMEOUT
    while time.time() < end:
        if p.proc.returncode is not None:
            return False
        raw = await kv().get(f"ext:ready:{p.id}")
        if raw and json.loads(raw).get("state") == "ready" and json.loads(raw).get("version", p.version) == p.version:
            return True
        await asyncio.sleep(0.3)
    return False


async def _kill(p: Proc) -> None:
    p.stopping = True
    if p.proc.returncode is not None:
        return
    try:
        os.killpg(p.proc.pid, signal.SIGTERM)
        await asyncio.wait_for(p.proc.wait(), 6)
    except ProcessLookupError, TimeoutError:
        try:
            os.killpg(p.proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    _log.info("ext_stopped", ext=p.id, pid=p.proc.pid)


async def stop(ext_id: str) -> None:
    p = procs.pop(ext_id, None)
    if p is not None:
        await _kill(p)
    await kv().delete(f"ext:proc:{ext_id}")


async def start(x: Extension, version: str | None = None) -> None:
    version = version or x.version
    m = x.manifest
    if m.get("type") == "z2m-converter":
        path = await _prepare(x, version)
        code = (path / m["converter"]).read_text("utf-8")
        await zigbee.converter(m["converter"], code)
        await set_status(x.id, "running", version=version)
        return
    path = _dest(x, version)
    if not (path / "manifest.json").exists():
        path = await _prepare(x, version)
    await set_status(x.id, "starting", version=version)
    p = await spawn(x, path, version)
    procs[x.id] = p
    if await ready(p):
        await set_status(x.id, "running", p.proc.pid, version=version)
    else:
        tail = list(reversed(await kv().lrange(f"ext:log:{x.id}", 0, 4)))
        await stop(x.id)
        crashes.setdefault(x.id, []).append(time.time())
        await set_status(x.id, "error", error="not ready: " + " | ".join(tail)[-400:])


async def op(name: str, ext_id: str) -> None:
    if ext_id in busy:
        return
    busy.add(ext_id)
    try:
        async with session() as s:
            x = await s.get(Extension, ext_id)
        if x is None:
            return
        _log.info("ext_op", op=name, ext=ext_id)
        if name in ("install", "start"):
            crashes.pop(ext_id, None)
            if name == "install":
                await _prepare(x, x.version)
            await start(x)
        elif name == "restart":
            crashes.pop(ext_id, None)
            await stop(ext_id)
            await start(x)
        elif name == "stop":
            await stop(ext_id)
            if x.manifest.get("type") == "z2m-converter":
                await zigbee.converter(x.manifest["converter"], None)
            await set_status(ext_id, "stopped")
        elif name == "update":
            e = extensions.entry(ext_id)
            if e is None:
                return
            new = e["manifest"]["version"]
            path = await _prepare(x, new)
            old = procs.get(ext_id)
            if x.manifest.get("type") == "z2m-converter":
                await start(x, new)
                return
            p = await spawn(x, path, new)
            if await ready(p):
                procs[ext_id] = p
                if old:
                    await _kill(old)
                await set_status(ext_id, "running", p.proc.pid, version=new)
            else:
                await _kill(p)
                tail = " | ".join(reversed(await kv().lrange(f"ext:log:{ext_id}", 0, 4)))[-300:]
                await set_status(
                    ext_id, "running" if old else "error", old.proc.pid if old else None, error=f"update failed: {tail}"
                )
        elif name == "remove":
            await stop(ext_id)
            if x.manifest.get("type") == "z2m-converter":
                try:
                    await zigbee.converter(x.manifest["converter"], None)
                except ApplicationError as e:
                    _log.warning("ext_converter_remove_failed", ext=ext_id, error=str(e))
            try:
                await mqttx.drop(f"ext-{ext_id}", f"ext-{ext_id}")
            except ApplicationError as e:
                _log.warning("ext_broker_role_remove_failed", ext=ext_id, error=str(e))
            if x.trust != "local":
                await asyncio.to_thread(
                    shutil.rmtree,
                    extensions.EXT_DIR / ext_id,
                    onexc=lambda _f, path, e: _log.warning("ext_files_remove_failed", path=path, error=str(e)),
                )
            await kv().delete(f"ext:log:{ext_id}", f"ext:ready:{ext_id}", f"ext:proc:{ext_id}", f"ext:cred:{ext_id}")
            async with session() as s:
                await extensions.purge(s, ext_id)
                await commit(s)
    except Exception as e:
        _log.error("ext_op_failed", op=name, ext=ext_id, error=str(e), exc_info=True)
        await set_status(ext_id, "error", error=str(e)[:400])
    finally:
        busy.discard(ext_id)


async def reconcile() -> None:
    async with session() as s:
        rows = (await s.scalars(select(Extension))).all()
    for x in rows:
        if x.status == "installing":
            await op("install", x.id)
        elif x.status == "updating":
            await op("update", x.id)
        elif x.status == "removing":
            await op("remove", x.id)
        elif x.enabled and x.id not in procs and x.manifest.get("type") != "z2m-converter":
            if x.status == "error" and len([t for t in crashes.get(x.id, []) if time.time() - t < 600]) >= MAX_RESTARTS:
                continue
            if x.status != "error" or not crashes.get(x.id):
                await op("start", x.id)
        elif not x.enabled and x.id in procs:
            await op("stop", x.id)


def _stats(p: Proc) -> dict[str, Any]:
    try:
        f = pathlib.Path(f"/proc/{p.proc.pid}/stat").read_text().split()
        ticks = (int(f[13]) + int(f[14])) / os.sysconf("SC_CLK_TCK")
        rss = int(pathlib.Path(f"/proc/{p.proc.pid}/statm").read_text().split()[1]) * os.sysconf("SC_PAGE_SIZE")
    except OSError, IndexError, ValueError:
        return {"pid": p.proc.pid, "up": time.time() - p.started}
    prev, at = p.cpu
    now = time.time()
    cpu = max(0.0, (ticks - prev) / (now - at) * 100) if prev else 0.0
    p.cpu = (ticks, now)
    return {"pid": p.proc.pid, "cpu": round(cpu, 1), "mem": round(rss / 1048576, 1), "up": round(now - p.started)}


async def monitor() -> None:
    n = 0
    while True:
        await beat("ext", 30)
        for p in list(procs.values()):
            stats = _stats(p)
            await kv().set(
                f"ext:proc:{p.id}", json.dumps({**stats, "limits": {"mem": p.limits[0], "cpu": p.limits[1]}}), ex=30
            )
            reason, p.hot = over(stats, *p.limits, p.hot)
            if reason and p.proc.returncode is None:
                _log.error("ext_limit", ext=p.id, reason=reason)
                p.reason = reason
                try:
                    os.killpg(p.proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                continue
            async with session() as s:
                x = await s.get(Extension, p.id)
            if x and x.trust == "local" and (m := _mtime(p.path)) > p.mtime:
                _log.info("ext_changed", ext=p.id)
                p.mtime = m
                await op("restart", p.id)
        n += 1
        if n % 6 == 0:
            await reconcile()
        await asyncio.sleep(5)


async def listen() -> None:
    ps = kv().pubsub()
    await ps.subscribe("ext:cmd")
    async for msg in ps.listen():
        if msg.get("type") != "message":
            continue
        try:
            data = json.loads(msg["data"])
            bg(op(data["op"], data["id"]))
        except (ValueError, KeyError) as e:
            _log.warning("ext_cmd_invalid", error=str(e))


async def main() -> None:
    log.setup("ext")
    await tasks.broker.startup()
    extensions.EXT_DIR.mkdir(parents=True, exist_ok=True)
    loop = asyncio.get_running_loop()
    stopping = asyncio.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stopping.set)
    await asyncio.sleep(2)
    await reconcile()
    jobs = [
        asyncio.create_task(forever("ext_monitor", monitor, _log)),
        asyncio.create_task(forever("ext_listen", listen, _log)),
    ]
    await stopping.wait()
    for t in jobs:
        t.cancel()
    for ext_id in list(procs):
        await stop(ext_id)


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
