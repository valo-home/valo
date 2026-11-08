import asyncio
import json
import time
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlsplit

import thinglogic as tl
from valo_camera import AuthError, Onvif, onvif_motion, sweep, tcp_open
from valo_sdk import Extension

ext = Extension()
watchers: dict[str, asyncio.Task] = {}
configs: dict[str, dict[str, Any]] = {}
states: dict[str, dict[str, Any]] = {}
infos: dict[str, dict[str, Any]] = {}
DISCOVER_EVERY = 600
GUARD_EVERY = 30
LOST_AFTER = 3


def _get(url: str, timeout: float = tl.TIMEOUT, method: str = "GET", body: Any = None) -> tuple[int, bytes]:
    data = json.dumps(body).encode() if body is not None else None
    headers = {"User-Agent": "valo-thingino"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(256 * 1024)
    except urllib.error.HTTPError as e:
        return e.code, e.read(4096) if e.fp else b""


async def get(url: str, method: str = "GET", body: Any = None, timeout: float = tl.TIMEOUT) -> tuple[int, bytes]:
    try:
        return await asyncio.to_thread(_get, url, timeout, method, body)
    except (OSError, TimeoutError) as e:
        raise tl.CameraError("camera does not answer over HTTP") from e


async def agent(cfg: dict[str, Any], path: str, method: str = "GET", body: Any = None) -> Any:
    code, raw = await get(tl.agent_url(cfg, path), method, body)
    if code == 401:
        raise AuthError("API key is wrong")
    try:
        data = json.loads(raw) if raw else {}
    except ValueError as e:
        raise tl.CameraError(f"{path} is not supported by this firmware") from e
    if code >= 400:
        raise tl.CameraError(f"{path} answered {code}")
    return data


async def cgi(cfg: dict[str, Any], path: str, body: Any = None, **params: Any) -> Any:
    code, raw = await get(tl.api_url(cfg, path, **params), "POST" if body is not None else "GET", body)
    if code == 401:
        raise AuthError("API key is wrong")
    if code >= 400:
        raise tl.CameraError(f"{path} answered {code}")
    try:
        return json.loads(raw) if raw else {}
    except ValueError:
        return None


async def identify(cfg: dict[str, Any]) -> dict[str, Any]:
    code, body = await get(tl.agent_url(cfg, "/api/v1/device"))
    if code == 401:
        raise AuthError("API key is wrong")
    if code == 200:
        try:
            return tl.info_of(json.loads(body))
        except ValueError:
            ext.log.warning("agent device answer is not JSON, falling back to heartbeat")
    code, _ = await get(tl.api_url(cfg, "/x/json-heartbeat-slow.cgi"))
    if code == 401:
        raise AuthError("API key is wrong")
    if code != 200:
        raise tl.CameraError(f"camera answered {code}, is it Thingino?")
    return tl.info_of({})


@ext.camera_probe
async def probe(cfg: dict[str, Any]) -> dict[str, Any]:
    info = await identify(cfg)
    main, sub = str(cfg.get("main") or "ch0"), str(cfg.get("sub", "ch1") or "").strip()
    await tl.rtsp_check(tl.rtsp_url(cfg, main))
    if sub:
        await tl.rtsp_check(tl.rtsp_url(cfg, sub))
    try:
        info["ptz"] = tl.motor_status(await cgi(cfg, "/x/json-motor.cgi", d="j")) is not None
    except tl.CameraError:
        info["ptz"] = False
    ext.log.info(
        "camera %s ok, model %s, firmware %s, ptz %s", tl.host_of(cfg), info["model"], info["firmware"], info["ptz"]
    )
    return {
        "streams": {"main": tl.rtsp_url(cfg, main), "sub": tl.rtsp_url(cfg, sub) if sub else ""},
        "stills": tl.stills(cfg),
        "info": info,
        "caps": [],
    }


async def events(cid: str, cfg: dict[str, Any], state: dict[str, Any]) -> None:
    """Поток событий агента камеры. Возвращается при обрыве, вызывающий переподключается."""
    u = urlsplit(tl.agent_url(cfg, "/api/v1/events"))
    host, _, port = u.netloc.partition(":")
    reader, writer = await asyncio.wait_for(asyncio.open_connection(host, int(port or 80)), tl.TIMEOUT)
    try:
        writer.write(
            f"GET {u.path}?{u.query} HTTP/1.0\r\nHost: {u.netloc}\r\nAccept: text/event-stream\r\n"
            "User-Agent: valo-thingino\r\n\r\n".encode()
        )
        await writer.drain()
        head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), tl.TIMEOUT)
        status = head.split(b"\r\n", 1)[0].decode(errors="replace")
        if " 404" in status:
            raise tl.Unsupported(status)
        if " 200" not in status:
            raise tl.CameraError(f"events endpoint answered {status}")
        sse = tl.Sse()
        first = True
        while True:
            line = await asyncio.wait_for(reader.readline(), 120)
            if not line:
                return
            text = line.decode(errors="replace")
            if first and text.strip():
                first = False
                if tl.sse_error(text.strip()):
                    raise tl.Unsupported(text.strip()[:120])
                await online(cid, state, True)
                ext.log.info("camera %s events connected", cid)
            got = sse.feed(text)
            if got is None:
                continue
            m = tl.motion_of(*got)
            if m is not None:
                await motion(cid, state, m)
    finally:
        writer.close()


async def online(cid: str, state: dict[str, Any], alive: bool, reason: str = "", detail: str = "") -> None:
    if state.get("online") != alive:
        await ext.available(cid, alive)
        state["online"] = alive
    why = "ok" if alive else (reason or "offline")
    if state.get("reason") != why or (not alive and state.get("detail") != detail):
        await ext.camera_health(cid, why, detail)
        state["reason"], state["detail"] = why, detail
    if not alive:
        await motion(cid, state, False)


async def motion(cid: str, state: dict[str, Any], active: bool) -> None:
    if state.get("moving") != active:
        await ext.camera_event(cid, "motion", active)
        state["moving"] = active


async def check(cid: str, cfg: dict[str, Any]) -> tuple[bool, str, str]:
    """Доступна ли камера и если нет, то почему: offline, other_device, auth_api."""
    try:
        code, _ = await get(tl.api_url(cfg, "/x/json-heartbeat-slow.cgi"))
    except tl.CameraError:
        host = tl.host_of(cfg).split(":")[0]
        if await tcp_open(host, 80, 2):
            return False, "other_device", f"{host} answers, but it is not this camera"
        return False, "offline", f"{host} does not answer"
    if code == 200:
        mac = str((infos.get(cid) or {}).get("mac") or "")
        if mac:
            try:
                dev = await agent(cfg, "/api/v1/device")
            except tl.CameraError:
                dev = None
            if isinstance(dev, dict) and dev.get("id") and not tl.same_camera(dev, mac):
                return False, "other_device", f"another Thingino camera {dev.get('hostname') or ''} answers"
        return True, "ok", ""
    try:
        _, page = await get(f"http://{tl.host_of(cfg)}/", timeout=4)
    except tl.CameraError:
        page = b""
    if not tl.is_thingino(page):
        return False, "other_device", f"{tl.host_of(cfg)} answers, but it is not a Thingino camera"
    if code == 401:
        return False, "auth_api", "API key is wrong"
    return False, "offline", f"camera answered {code}"


async def find(cid: str, cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Найти камеры Thingino в сети /24 прежнего адреса. Ключ API отправляется только камерам Thingino."""
    mac = str((infos.get(cid) or {}).get("mac") or "")
    hosts = tl.subnet_hosts(tl.host_of(cfg))
    if not hosts:
        raise tl.CameraError("search works only for an IPv4 address")
    found: list[dict[str, Any]] = []
    for h in await sweep(hosts, 80, limit=64, timeout=1.0):
        try:
            code, page = await get(f"http://{h}/", timeout=3)
        except tl.CameraError:
            continue
        if code != 200 or not tl.is_thingino(page):
            continue
        item: dict[str, Any] = {"host": h, "mac": "", "model": "", "hostname": "", "same": False}
        try:
            dev = await agent({**cfg, "host": h}, "/api/v1/device")
            item.update(
                mac=str(dev.get("id") or ""),
                model=str(dev.get("model") or ""),
                hostname=str(dev.get("hostname") or ""),
                same=tl.same_camera(dev, mac),
            )
        except tl.CameraError as e:
            item["hostname"] = str(e)
        found.append(item)
    ext.log.info("camera %s search: %d Thingino cameras in the network", cid, len(found))
    return found


async def onvif(cid: str, cfg: dict[str, Any], state: dict[str, Any], until: float) -> None:
    """События движения по ONVIF PullPoint для прошивок без потока событий агента."""
    ov = Onvif(tl.host_of(cfg).split(":")[0], str(cfg.get("user") or "thingino"), str(cfg.get("password") or ""))
    addr = await ov.subscribe(300)
    born = time.monotonic()
    await online(cid, state, True)
    ext.log.info("camera %s ONVIF events subscribed", cid)
    try:
        while time.monotonic() < until:
            if time.monotonic() - born > 240:
                try:
                    await ov.renew(addr, 300)
                except tl.CameraError as e:
                    ext.log.info("camera %s ONVIF renew failed (%s), subscribing again", cid, e)
                    addr = await ov.subscribe(300)
                born = time.monotonic()
            m = onvif_motion(await ov.pull(addr, 20))
            await online(cid, state, True)
            if m is not None:
                await motion(cid, state, m)
    finally:
        try:
            await ov.unsubscribe(addr)
        except tl.CameraError as e:
            ext.log.info("camera %s ONVIF unsubscribe failed: %s", cid, e)


async def watch(cid: str, cfg: dict[str, Any]) -> None:
    state = states.setdefault(cid, {"online": None, "moving": None, "reason": None})
    delay, source = 5.0, "agent"
    while True:
        started = time.monotonic()
        try:
            if source == "agent":
                await events(cid, cfg, state)
                reason = "events stream closed"
            else:
                await onvif(cid, cfg, state, time.monotonic() + 3600)
                continue
        except tl.Unsupported as e:
            ext.log.info("camera %s has no agent events (%s), using ONVIF events", cid, e)
            source = "onvif"
            continue
        except tl.CameraError as e:
            reason = str(e)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            reason = f"{type(e).__name__}: {e}"
        try:
            ok, why, detail = await check(cid, cfg)
            await online(cid, state, ok, why, detail)
            if ok:
                state["fails"] = 0
            else:
                await relocate(cid, cfg, state)
        except Exception as e:
            ok = False
            ext.log.error("camera %s state not reported: %s", cid, e)
        ext.log.warning(
            "camera %s %s events interrupted: %s, camera %s", cid, source, reason, "online" if ok else "offline"
        )
        if time.monotonic() - started > 120:
            delay = 5.0
        await asyncio.sleep(delay)
        delay = min(delay * 2, 60.0)


async def relocate(cid: str, cfg: dict[str, Any], state: dict[str, Any]) -> None:
    """После нескольких неудачных проверок подряд поискать камеру по сети и сообщить ядру новый адрес."""
    state["fails"] = state.get("fails", 0) + 1
    if state["fails"] < LOST_AFTER or not (infos.get(cid) or {}).get("mac"):
        return
    if time.monotonic() - state.get("searched", -DISCOVER_EVERY) < DISCOVER_EVERY:
        return
    state["searched"] = time.monotonic()
    try:
        found = await find(cid, cfg)
    except tl.CameraError as e:
        ext.log.warning("camera %s search failed: %s", cid, e)
        return
    match = next((f["host"] for f in found if f["same"]), None)
    if match and match != tl.host_of(cfg):
        ext.log.warning("camera %s found at %s, was %s", cid, match, tl.host_of(cfg))
        await ext.camera_moved(cid, match)
        cfg["host"] = match
        state["fails"] = 0
        ext.log.info("camera %s now watched at %s", cid, match)


async def streamer_ok(cfg: dict[str, Any]) -> bool | None:
    """Работает ли видеосервис на камере. None, если камера не ответила."""
    try:
        h = await agent(cfg, "/api/v1/health")
    except tl.CameraError:
        return None
    return tl.streamer_running(h)


async def revive(cid: str, cfg: dict[str, Any], why: str) -> bool:
    """Запустить упавший видеосервис камеры и дождаться порта RTSP."""
    state = states.setdefault(cid, {"online": None, "moving": None, "reason": None})
    ext.log.warning("camera %s video service is stopped (%s), starting it", cid, why)
    await ext.camera_health(cid, "no_video", f"video service on the camera stopped ({why}), restarting")
    state["reason"] = "no_video"
    try:
        await agent(cfg, "/api/v1/actions/services/streaming/start", "POST", {})
    except tl.CameraError as e:
        ext.log.error("camera %s video service not started: %s", cid, e)
        return False
    host = tl.host_of(cfg).split(":")[0]
    for _ in range(20):
        await asyncio.sleep(1.5)
        if await tcp_open(host, 554, 2):
            ext.log.info("camera %s video service is running again", cid)
            await ext.camera_health(cid, "ok")
            state["reason"] = "ok"
            return True
    ext.log.error("camera %s video service did not come back", cid)
    return False


@ext.loop
async def guard() -> None:
    """Раз в 30 секунд проверять видеосервис каждой камеры. Прошивка может уронить его, например при
    переключении детекции движения на ходу, а события ONVIF при этом продолжают идти."""
    down: dict[str, int] = {}
    while True:
        await asyncio.sleep(GUARD_EVERY)
        for cid, cfg in list(configs.items()):
            try:
                ok = await streamer_ok(cfg)
                if ok is False:
                    down[cid] = down.get(cid, 0) + 1
                    if down[cid] >= 2:
                        await revive(cid, cfg, "found by the periodic check")
                        down[cid] = 0
                else:
                    down.pop(cid, None)
            except Exception as e:
                ext.log.error("camera %s video service check failed: %s", cid, e)


@ext.camera_sync
async def sync(cameras: list[dict[str, Any]]) -> dict[str, Any]:
    for c in cameras:
        if c.get("id"):
            infos[c["id"]] = c.get("info") or infos.get(c["id"]) or {}
    wanted = {c["id"]: c.get("config") or {} for c in cameras if c.get("id")}
    for st in states.values():
        st["online"] = st["moving"] = st["reason"] = None
    for cid in list(watchers):
        if cid not in wanted or configs.get(cid) != wanted[cid]:
            watchers.pop(cid).cancel()
            configs.pop(cid, None)
            states.pop(cid, None)
    for cid, cfg in wanted.items():
        if cid not in watchers or watchers[cid].done():
            configs[cid] = cfg
            watchers[cid] = asyncio.ensure_future(watch(cid, cfg))
    ext.log.info("watching %d cameras", len(watchers))
    return {"watching": sorted(watchers)}


async def _schema(cfg: dict[str, Any]) -> Any:
    try:
        return await agent(cfg, "/api/v1/config/schema")
    except tl.CameraError as e:
        ext.log.warning("camera %s settings schema unavailable, writable settings unknown: %s", tl.host_of(cfg), e)
        return {}


async def _fields(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    doc = await agent(cfg, "/api/v1/config")
    hb, schema, tm = await asyncio.gather(
        cgi(cfg, "/x/json-heartbeat-slow.cgi"), _schema(cfg), cgi(cfg, "/x/json-config-time.cgi")
    )
    return tl.fields_of(doc, hb, schema, tm, time.time())


@ext.camera_feature("settings")
async def settings(params: dict[str, Any]) -> dict[str, Any]:
    cfg = params.get("config") or {}
    if params.get("op") != "set":
        return {"fields": await _fields(cfg)}
    schema = await _schema(cfg)
    failed: dict[str, str] = {}
    for key, value in (params.get("values") or {}).items():
        try:
            for method, path, body in tl.patch_of(str(key), value, schema):
                res = await agent(cfg, path, method, body)
                if not tl.accepted(res):
                    raise tl.CameraError(str(res)[:160])
            ext.log.info("camera %s setting %s changed", params.get("camera"), key)
        except tl.CameraError as e:
            failed[str(key)] = str(e)
            ext.log.warning("camera %s setting %s not changed: %s", params.get("camera"), key, e)
    await asyncio.sleep(3)
    if await streamer_ok(cfg) is False:
        await revive(str(params.get("camera") or ""), cfg, "stopped after a settings change")
    return {"fields": await _fields(cfg), "failed": failed}


@ext.camera_feature("actions")
async def actions(params: dict[str, Any]) -> dict[str, Any]:
    cfg, name = params.get("config") or {}, params.get("action")
    extra = params.get("params") or {}
    if name == "reboot":
        await agent(cfg, "/api/v1/actions/reboot", "POST", {})
        ext.log.warning("camera %s reboot requested", params.get("camera"))
        return {"ok": True, "detail": "rebooting, about 60 s"}
    if name == "restart_stream":
        await agent(cfg, "/api/v1/actions/services/streaming/restart", "POST", {})
        return {"ok": True, "detail": "stream restarting"}
    if name == "sync_time":
        cur = await cgi(cfg, "/x/json-config-time.cgi") or {}
        tz = str(extra.get("timezone") or cur.get("tz_name") or "UTC")
        posix = tl.tz_posix(tz) or (str(cur.get("tz_data") or "") if tz == cur.get("tz_name") else "")
        if not posix:
            raise tl.CameraError(f"time zone {tz} is unknown")
        body = tl.time_config(cur, tz, posix, str(extra.get("ntp") or ""))
        res = await cgi(cfg, "/x/json-config-time.cgi", body)
        if not isinstance(res, dict) or res.get("status") != "ok":
            raise tl.CameraError(f"time was not set: {str(res)[:160]}")
        detail = f"{body['tz_name']}, {body['ntp_server_0']}"
        try:
            done = await cgi(cfg, "/x/json-sync-time.cgi")
        except tl.CameraError as e:
            ext.log.warning("camera %s time saved, but not synchronized now: %s", params.get("camera"), e)
            return {"ok": True, "detail": f"{detail}, synchronization on the next poll"}
        if not isinstance(done, dict) or done.get("result") != "success":
            ext.log.warning("camera %s time not synchronized: %s", params.get("camera"), str(done)[:160])
            return {"ok": True, "detail": f"{detail}, synchronization on the next poll"}
        return {"ok": True, "detail": f"{detail}, synchronized"}
    raise tl.CameraError(f"action {name} is not supported")


@ext.camera_feature("diagnose")
async def diagnose(params: dict[str, Any]) -> dict[str, Any]:
    cfg = params.get("config") or {}
    cid = str(params.get("camera") or "")
    host = tl.host_of(cfg).split(":")[0]
    checks: list[dict[str, Any]] = []

    def add(key: str, ok: bool | None, value: Any = None, detail: str = "") -> None:
        checks.append({"key": key, "ok": ok, "value": value, "detail": detail})

    web = await tcp_open(host, 80, 3)
    add("network", web or await tcp_open(host, 554, 3), host)
    if not web:
        add("web", False, None, f"{host}:80 does not answer")
        return {"checks": checks}
    try:
        dev = await agent(cfg, "/api/v1/device")
        mac = str((params.get("info") or {}).get("mac") or "")
        add("identity", not mac or tl.same_camera(dev, mac), str(dev.get("hostname") or ""), str(dev.get("id") or ""))
        add("firmware", True, str((dev.get("software") or {}).get("firmware_version") or ""))
        add("api_key", True)
    except AuthError as e:
        add("api_key", False, None, str(e))
    except tl.CameraError as e:
        add("web", False, None, str(e))
    for name in ("main", "sub"):
        ch = str(cfg.get(name) or ("ch0" if name == "main" else "")).strip()
        if not ch:
            continue
        try:
            await tl.rtsp_check(tl.rtsp_url(cfg, ch))
            add(f"rtsp_{name}", True, ch)
        except tl.CameraError as e:
            add(f"rtsp_{name}", False, ch, str(e))
    try:
        await Onvif(host, str(cfg.get("user") or "thingino"), str(cfg.get("password") or "")).call(
            "/onvif/device_service",
            '<tds:GetSystemDateAndTime xmlns:tds="http://www.onvif.org/ver10/device/wsdl"/>',
        )
        add("onvif", True)
    except Exception as e:
        add("onvif", False, None, str(e)[:160])
    try:
        health = await agent(cfg, "/api/v1/health")
        sysd = (health.get("checks") or {}).get("system") or {}
        add("uptime", True, sysd.get("uptime_seconds"))
        add("load", (sysd.get("load_average_1m") or 0) < 8, sysd.get("load_average_1m"))
        total, avail = sysd.get("memory_total_kib") or 0, sysd.get("memory_available_kib") or 0
        add("memory", not total or avail / total > 0.1, round(avail / 1024, 1) if avail else None)
        add("streamer", bool(sysd.get("streamer_running")))
    except tl.CameraError as e:
        add("health", False, None, str(e))
    try:
        hb = await cgi(cfg, "/x/json-heartbeat-slow.cgi") or {}
        ts = hb.get("time_now")
        if isinstance(ts, (int, float)):
            drift = round(ts - time.time())
            add("clock", abs(drift) < 30, drift)
    except tl.CameraError as e:
        add("clock", None, None, str(e))
    ext.log.info("camera %s diagnose: %d checks", cid, len(checks))
    return {"checks": checks}


@ext.camera_feature("discover")
async def discover(params: dict[str, Any]) -> dict[str, Any]:
    cid = str(params.get("camera") or "")
    if params.get("info"):
        infos[cid] = params["info"]
    return {"found": await find(cid, params.get("config") or {})}


async def motors(cfg: dict[str, Any], **q: Any) -> Any:
    res = await cgi(cfg, "/x/json-motor.cgi", **q)
    if res is None:
        raise tl.CameraError("this camera has no motors")
    if isinstance(res, dict) and res.get("error"):
        raise tl.CameraError(str(res["error"].get("message") if isinstance(res["error"], dict) else res["error"]))
    return res


async def stopped(cfg: dict[str, Any], limit: float = 20) -> Any:
    """Дождаться остановки моторов. Команда во время поворота выполняется неправильно."""
    end = time.monotonic() + limit
    res = await motors(cfg, d="j")
    while tl.motor_busy(res) and time.monotonic() < end:
        await asyncio.sleep(0.3)
        res = await motors(cfg, d="j")
    return res


@ext.camera_feature("ptz")
async def ptz(params: dict[str, Any]) -> dict[str, Any]:
    cfg, op = params.get("config") or {}, params.get("op")
    if op == "stop":
        await motors(cfg, d="s")
        return {"position": tl.motor_status(await stopped(cfg, 5))}
    if op not in ("move", "goto", "home", "calibrate", "position"):
        raise tl.CameraError(f"operation {op} is not supported")
    if op == "position":
        return {"position": tl.motor_status(await motors(cfg, d="j"))}
    lim = tl.motor_limits(await motors(cfg, d="i"))
    await stopped(cfg)
    if op == "move":
        dx, dy = tl.jog_steps(float(params.get("pan") or 0), float(params.get("tilt") or 0), *lim)
        if dx or dy:
            await motors(cfg, d="g", x=dx, y=dy)
    elif op == "goto":
        pos = params.get("position") or {}
        x = max(0, min(int(pos.get("x", 0)), lim[0]))
        y = max(0, min(int(pos.get("y", 0)), lim[1]))
        await motors(cfg, d="h", x=x, y=y)
    elif op == "home":
        await motors(cfg, d="b")
    else:
        await motors(cfg, d="r")
        ext.log.warning("camera %s motors calibration started", params.get("camera"))
        return {"position": None}
    await asyncio.sleep(0.4)
    return {"position": tl.motor_status(await stopped(cfg))}


if __name__ == "__main__":
    ext.run()
