import asyncio
import base64
import inspect
import json
import logging
import os
import pathlib
import signal
import sys
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import aiomqtt
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.properties import Properties

Handler = Callable[..., Awaitable[Any] | Any]


def _props(response: str | None = None, corr: bytes | str | None = None) -> Properties | None:
    if not (response or corr):
        return None
    p = Properties(PacketTypes.PUBLISH)
    if response:
        p.ResponseTopic = response
    if corr:
        p.CorrelationData = corr if isinstance(corr, bytes) else corr.encode()
    return p


async def _maybe(v: Any) -> Any:
    return await v if inspect.isawaitable(v) else v


class Extension:
    def __init__(self) -> None:
        self.id = os.environ["VALO_EXT_ID"]
        self.version = os.environ.get("VALO_EXT_VERSION", "0")
        self.settings: dict[str, Any] = json.loads(os.environ.get("VALO_EXT_SETTINGS") or "{}")
        self.data = pathlib.Path(os.environ.get("VALO_EXT_DATA", "."))
        self.demo = os.environ.get("VALO_DEMO", "").lower() in ("1", "true", "yes")
        self.lang = "en"
        self.base = f"hub/v1/ext/{self.id}"
        self.client: aiomqtt.Client | None = None
        self._blocks: dict[str, Handler] = {}
        self._services: dict[str, Handler] = {}
        self._pages: dict[str, Handler] = {}
        self._setters: dict[str, Handler] = {}
        self._devices: dict[str, dict[str, Any]] = {}
        self._subs: dict[str, Handler] = {}
        self._loops: list[Handler] = []
        self._calls: dict[str, asyncio.Future] = {}
        self._tasks: set[asyncio.Task] = set()
        self._starters: list[Handler] = []
        self._probe: Handler | None = None
        self._sync: Handler | None = None
        self._cam: dict[str, Handler] = {}
        logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="%(asctime)s %(levelname)s %(message)s")
        self.log = logging.getLogger(self.id)

    def block(self, key: str) -> Callable[[Handler], Handler]:
        return lambda fn: self._blocks.__setitem__(key, fn) or fn

    def service(self, name: str) -> Callable[[Handler], Handler]:
        return lambda fn: self._services.__setitem__(name, fn) or fn

    def page(self, method: str) -> Callable[[Handler], Handler]:
        return lambda fn: self._pages.__setitem__(method, fn) or fn

    def on_set(self, device: str) -> Callable[[Handler], Handler]:
        return lambda fn: self._setters.__setitem__(device, fn) or fn

    def subscribe(self, topic: str) -> Callable[[Handler], Handler]:
        return lambda fn: self._subs.__setitem__(topic, fn) or fn

    def loop(self, fn: Handler) -> Handler:
        self._loops.append(fn)
        return fn

    def on_start(self, fn: Handler) -> Handler:
        self._starters.append(fn)
        return fn

    def camera_probe(self, fn: Handler) -> Handler:
        """Драйвер камеры. fn(config) проверяет камеру по полям из manifest.camera.fields и возвращает
        {"streams": {"main": url, "sub": url}, "stills": {"snapshot": url, "preview": url},
        "info": {"model", "vendor", "firmware", ...}, "caps": [...]}. Ошибка в fn означает, что камера не добавится.
        """
        self._probe = fn
        return fn

    def camera_sync(self, fn: Handler) -> Handler:
        """Драйвер камеры. fn(cameras) получает список своих камер [{"id", "config"}] при старте и после
        каждого изменения в интерфейсе. Драйвер запускает и останавливает по нему слежение за событиями.
        """
        self._sync = fn
        return fn

    def camera_feature(self, name: str) -> Callable[[Handler], Handler]:
        """Драйвер камеры. fn(params) обрабатывает запрос camera.<name> и должен быть перечислен в
        manifest.camera.features. params содержит camera, config, info и поля запроса:
        settings {"op": "get"|"set", "values"} -> {"fields": [...], "failed": {key: text}}
        actions {"action": "reboot"|"restart_stream"|"sync_time", "params"} -> {"ok", "detail"}
        diagnose {} -> {"checks": [{"key", "ok", "value", "detail"}]}
        discover {} -> {"found": [{"host", "mac", "model", "hostname", "same"}]}
        ptz {"op": "move"|"stop"|"home"|"goto"|"position"|"calibrate", "pan", "tilt", "speed", "position"}
        -> {"position": {...}}
        """
        return lambda fn: self._cam.__setitem__(name, fn) or fn

    async def camera_health(self, camera: str, reason: str, detail: str = "") -> Any:
        """Состояние связи со своей камерой: ok, offline, unreachable, other_device, auth_api, auth_stream,
        no_video, starting. Интерфейс показывает его вместо общего Подключение.
        """
        return await self.call("cameras.health", {"camera": camera, "reason": reason, "detail": detail[:200]})

    async def camera_moved(self, camera: str, host: str) -> Any:
        """Своя камера найдена по новому адресу. Ядро сохраняет адрес и заново проверяет потоки."""
        return await self.call("cameras.moved", {"camera": camera, "host": host}, timeout=20)

    async def camera_frame(self, camera: str, sub: bool = True, fresh: bool = False) -> bytes:
        """Текущий кадр камеры в JPEG (cameras.stream)."""
        res = await self.call("cameras.frame", {"camera": camera, "sub": sub, "fresh": fresh}, timeout=20)
        return base64.b64decode(res["data"])

    async def media_put(
        self,
        camera: str,
        data: bytes,
        event: int | None = None,
        label: str = "",
        meta: dict[str, Any] | None = None,
    ) -> Any:
        """Сохранить свой снимок JPEG в записи камеры и привязать к событию (media.write)."""
        return await self.call(
            "media.put",
            {
                "camera": camera,
                "data": base64.b64encode(data).decode(),
                "event": event,
                "label": label,
                "meta": meta or {},
            },
            timeout=30,
        )

    async def camera_event(
        self,
        camera: str,
        label: str = "motion",
        active: bool | None = True,
        score: float | None = None,
        data: dict[str, Any] | None = None,
    ) -> Any:
        """Сообщить событие камеры. active True начало, False конец, None мгновенное (например распознан человек).
        Нужно право cameras.provide для своих камер или cameras.events для любых.
        """
        return await self.call(
            "cameras.event",
            {"camera": camera, "label": label, "active": active, "score": score, "data": data or {}},
        )

    async def cameras(self) -> Any:
        """Камеры дома (cameras.stream, cameras.events или media.read)."""
        return await self.call("cameras.list")

    async def camera_stream(self, camera: str, sub: bool = True) -> Any:
        """Внутренний адрес RTSP потока камеры для анализа, {"rtsp", "sub"} (cameras.stream)."""
        return await self.call("cameras.stream", {"camera": camera, "sub": sub})

    async def snapshot(self, camera: str) -> Any:
        """Снять кадр и сохранить в хранилище, возвращает запись медиа (media.write)."""
        return await self.call("cameras.snapshot", {"camera": camera}, timeout=20)

    async def clip(self, camera: str, seconds: int = 15) -> Any:
        """Записать клип в хранилище (media.write). Запись появится через seconds секунд."""
        return await self.call("cameras.clip", {"camera": camera, "seconds": seconds})

    async def media(self, media_id: str) -> Any:
        """Запись медиа с содержимым в base64 в поле data, до 52 МБ (media.read)."""
        return await self.call("media.get", {"id": media_id}, timeout=30)

    def device(
        self,
        dev: str,
        name: str | dict[str, str],
        caps: list[dict[str, Any]],
        kind: str | None = None,
        model: str = "",
        service: bool | None = None,
    ) -> None:
        """Объявить запись расширения. name строка или словарь по языкам, имя выбирается по языку дома при создании.

        service=True для сервиса (данные или функция без своего прибора: погода, учет, охрана), service=False для
        прибора, который расширение подключает или имитирует. Без указания ядро решает по виду записи.
        """
        meta: dict[str, Any] = {"name": name, "caps": caps, "kind": kind, "model": model or self.id, "vendor": self.id}
        if service is not None:
            meta["service"] = bool(service)
        self._devices[dev] = meta

    async def _home_lang(self) -> str:
        try:
            home = await self.call("home", timeout=5)
        except Exception as e:
            self.log.warning("home language unavailable, device names fall back to English: %s", e)
            return "en"
        return str(home.get("lang") or "en") if isinstance(home, dict) else "en"

    @staticmethod
    def _pick(name: str | dict[str, str], lang: str) -> str:
        if not isinstance(name, dict):
            return str(name)
        return str(name.get(lang) or name.get("en") or next(iter(name.values()), ""))

    async def _pub(self, topic: str, payload: Any, retain: bool = False, props: Properties | None = None) -> None:
        if self.client is None:
            raise RuntimeError("not connected")
        await self.client.publish(
            topic,
            json.dumps(payload, default=str) if not isinstance(payload, str) else payload,
            qos=1,
            retain=retain,
            properties=props,
        )

    async def state(self, dev: str, values: dict[str, Any]) -> None:
        await self._pub(f"{self.base}/dev/{dev}/state", values, retain=True)

    async def available(self, dev: str, online: bool) -> None:
        await self._pub(f"{self.base}/dev/{dev}/avail", "online" if online else "offline", retain=True)

    async def changed(self, *keys: str) -> None:
        """Сообщить, что данные страниц или виджетов с этими ключами изменились, интерфейс перечитает их."""
        await self._pub(f"{self.base}/changed", {"keys": [str(k) for k in keys]})

    async def trigger(self, key: str, payload: Any = None) -> None:
        await self._pub(f"{self.base}/trigger/{key}", payload if payload is not None else {})

    async def call(self, method: str, params: dict[str, Any] | None = None, timeout: float = 10) -> Any:
        corr = uuid.uuid4().hex
        fut = asyncio.get_running_loop().create_future()
        self._calls[corr] = fut
        try:
            await self._pub(
                f"{self.base}/call",
                {"method": method, "params": params or {}},
                props=_props(f"{self.base}/reply", corr),
            )
            res = await asyncio.wait_for(fut, timeout)
        finally:
            self._calls.pop(corr, None)
        if isinstance(res, dict) and res.get("error"):
            raise RuntimeError(res["error"])
        return res.get("result") if isinstance(res, dict) else res

    def spawn(self, coro: Awaitable[Any]) -> None:
        t = asyncio.ensure_future(coro)
        self._tasks.add(t)
        t.add_done_callback(self._done)

    def _done(self, t: asyncio.Future) -> None:
        self._tasks.discard(t)
        if not t.cancelled() and t.exception() is not None:
            self.log.error("task failed: %r", t.exception(), exc_info=t.exception())

    async def _rpc(self, m: aiomqtt.Message, req: dict[str, Any]) -> None:
        method, params = str(req.get("method", "")), req.get("params") or {}
        try:
            if method == "block":
                fn = self._blocks[params["key"]]
                result = await _maybe(
                    fn(params.get("params") or {}, params.get("token") or {}, bool(params.get("dry")))
                )
            elif method == "service":
                result = await _maybe(self._services[params["name"]](params))
            elif method.startswith("page."):
                result = await _maybe(self._pages[method[5:]](params))
            elif method == "camera.probe" and self._probe:
                result = await _maybe(self._probe(params.get("config") or {}))
            elif method == "camera.sync" and self._sync:
                result = await _maybe(self._sync(params.get("cameras") or []))
            elif method.startswith("camera.") and method[7:] in self._cam:
                result = await _maybe(self._cam[method[7:]](params))
            elif method == "ping":
                result = {"ok": True}
            else:
                raise KeyError(method)
            body = {"result": result}
        except Exception as e:
            self.log.exception("rpc %s failed", method)
            body = {"error": f"{type(e).__name__}: {e}"}
        resp = getattr(m.properties, "ResponseTopic", None) if m.properties else None
        if resp:
            await self._pub(resp, body, props=_props(corr=getattr(m.properties, "CorrelationData", None)))

    async def _set(self, dev: str, req: dict[str, Any]) -> None:
        fn = self._setters.get(dev)
        cmd = req.get("cmd")
        try:
            values = await _maybe(fn(req.get("values") or {})) if fn else None
            if values:
                await self.state(dev, values)
            await self._pub(
                f"{self.base}/dev/{dev}/ack",
                {"cmd": cmd, "ok": fn is not None, "values": values or {}, "error": None if fn else "read only"},
            )
        except ValueError as e:
            self.log.warning("set %s rejected: %s", dev, e)
            await self._pub(f"{self.base}/dev/{dev}/ack", {"cmd": cmd, "ok": False, "values": {}, "error": str(e)})
        except Exception as e:
            self.log.exception("set %s failed", dev)
            await self._pub(f"{self.base}/dev/{dev}/ack", {"cmd": cmd, "ok": False, "error": str(e)})

    async def _handle(self, m: aiomqtt.Message) -> None:
        t = m.topic.value
        raw = m.payload.decode() if isinstance(m.payload, (bytes, bytearray)) else str(m.payload or "")
        try:
            payload = json.loads(raw) if raw else {}
        except ValueError:
            payload = raw
        if t == f"{self.base}/rpc":
            self.spawn(self._rpc(m, payload))
        elif t == f"{self.base}/reply":
            corr = getattr(m.properties, "CorrelationData", b"") if m.properties else b""
            fut = self._calls.get(corr.decode() if isinstance(corr, bytes) else str(corr))
            if fut and not fut.done():
                fut.set_result(payload)
        elif t.startswith(f"{self.base}/dev/") and t.endswith("/set"):
            self.spawn(self._set(t.split("/")[-2], payload))
        else:
            for pattern, fn in self._subs.items():
                if aiomqtt.Topic(t).matches(pattern):
                    self.spawn(_maybe(fn(t, payload)))

    async def _main(self) -> None:
        host, port = os.environ.get("VALO_MQTT_HOST", "localhost"), int(os.environ.get("VALO_MQTT_PORT", "1883"))
        will = aiomqtt.Will(f"{self.base}/status", json.dumps({"state": "offline"}), qos=1, retain=True)
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stop.set)
        stopper = asyncio.ensure_future(stop.wait())
        first, delay = True, 1.0
        while not stop.is_set():
            try:
                async with aiomqtt.Client(
                    host,
                    port,
                    username=os.environ.get("VALO_MQTT_USER"),
                    password=os.environ.get("VALO_MQTT_PASSWORD"),
                    identifier=f"ext-{self.id}-{os.getpid()}",
                    protocol=aiomqtt.ProtocolVersion.V5,
                    will=will,
                ) as c:
                    self.client = c
                    for topic in (f"{self.base}/rpc", f"{self.base}/reply", f"{self.base}/dev/+/set", *self._subs):
                        await c.subscribe(topic, qos=1)
                    reader = asyncio.ensure_future(self._read(c))
                    await self._online(first)
                    first, delay = False, 1.0
                    await asyncio.wait({reader, stopper}, return_when=asyncio.FIRST_COMPLETED)
                    if stop.is_set():
                        await self._pub(
                            f"{self.base}/status",
                            {"state": "stopping", "pid": os.getpid(), "version": self.version},
                            retain=True,
                        )
                        reader.cancel()
                        break
                    reader.result()
            except aiomqtt.MqttError as e:
                self.client = None
                if stop.is_set():
                    break
                self.log.warning("broker connection lost (%s), reconnecting in %s s", e, delay)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30.0)

    async def _online(self, first: bool) -> None:
        """Объявить записи и готовность. При переподключении к брокеру повторяется, циклы не запускаются заново."""
        if first and any(isinstance(m["name"], dict) for m in self._devices.values()):
            self.lang = await self._home_lang()
        for dev, meta in self._devices.items():
            await self._pub(
                f"{self.base}/dev/{dev}/meta", meta | {"name": self._pick(meta["name"], self.lang)}, retain=True
            )
            await self._pub(f"{self.base}/dev/{dev}/avail", "online", retain=True)
        if first:
            for fn in self._starters:
                await _maybe(fn())
            for fn in self._loops:
                self.spawn(fn())
        if self._sync:
            self.spawn(self._first_sync())
        await self._pub(
            f"{self.base}/status", {"state": "ready", "pid": os.getpid(), "version": self.version}, retain=True
        )
        self.log.info("%s %s %s", "ready" if first else "reconnected", self.id, self.version)

    async def _first_sync(self) -> None:
        delay = 5.0
        while True:
            try:
                cams = await self.call("cameras.mine", timeout=15)
                break
            except Exception as e:
                self.log.error("camera list unavailable, retry in %s s: %s", delay, e)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 120.0)
        if self._sync:
            await _maybe(self._sync(cams or []))

    async def _read(self, c: aiomqtt.Client) -> None:
        async for m in c.messages:
            try:
                await self._handle(m)
            except Exception:
                self.log.exception("message %s failed", m.topic.value)

    def run(self) -> None:
        asyncio.run(self._main())
