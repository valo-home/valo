import asyncio
import json
import time
from typing import Any

import aiomqtt
import msgspec
from paho.mqtt.client import topic_matches_sub

from app.db.base import commit, session
from app.domain import devices, events, extensions, ingest, mqttx
from app.lib import log, mqtt, realtime, tasks
from app.lib.errors import ApplicationError
from app.lib.kv import beat, kv
from app.lib.loops import forever
from app.lib.settings import env, settings

_log = log.get("mqtt_proc")
DYN_RESP = f"{mqttx.DYNSEC}/response"


class State:
    client: aiomqtt.Client | None = None
    index: dict[str, list[list[str]]] = {}
    filters: set[str] = set()
    flows_mqtt = False
    stats = {"n": 0, "t": time.time()}


async def refresh() -> None:
    async with session() as s:
        State.index = await devices.index(s)
    State.filters = set(await kv().smembers("flows:mqtt"))
    State.flows_mqtt = bool(await kv().sismember("flows:trig", "mqtt"))
    _log.info("index_refreshed", topics=len(State.index), filters=len(State.filters))


def corr_of(m: aiomqtt.Message) -> str | None:
    cd = getattr(m.properties, "CorrelationData", None) if m.properties else None
    return cd.decode(errors="replace") if isinstance(cd, (bytes, bytearray)) else None


async def ext_message(ext_id: str, rest: str, m: aiomqtt.Message, payload: Any) -> None:
    if rest == "status":
        await kv().set(
            f"ext:ready:{ext_id}",
            json.dumps(payload if isinstance(payload, dict) else {"state": str(payload)}),
            ex=3600,
        )
        state = payload.get("state") if isinstance(payload, dict) else str(payload)
        if state == "offline":
            async with session() as s:
                n = await devices.ext_offline(s, ext_id)
                await commit(s)
            if n:
                _log.warning("ext_devices_offline", ext=ext_id, devices=n, state=state)
    elif rest == "log":
        line = str(payload if isinstance(payload, str) else json.dumps(payload))[:2000]
        await kv().lpush(f"ext:log:{ext_id}", line)
        await kv().ltrim(f"ext:log:{ext_id}", 0, 499)
        await realtime.emit("ext_log", {"ext": ext_id, "line": line}, [f"extlog:{ext_id}"], durable=False)
    elif rest == "call":
        resp = getattr(m.properties, "ResponseTopic", None) if m.properties else None
        corr = corr_of(m)
        body: dict[str, Any]
        try:
            async with session() as s:
                result = await extensions.core_call(
                    s, ext_id, str(payload.get("method", "")), payload.get("params") or {}
                )
                await commit(s)
            body = {"result": msgspec.to_builtins(result)}
        except ApplicationError as e:
            body = {"error": e.code, "params": e.params}
        except Exception as e:
            _log.error("ext_call_failed", ext=ext_id, error=str(e), exc_info=True)
            body = {"error": "internal"}
        if resp:
            await mqtt.publish(resp, body, qos=1, properties=mqtt.props(correlation=corr))
    elif rest == "changed":
        keys = payload.get("keys") if isinstance(payload, dict) else None
        if isinstance(keys, list):
            clean = [k for k in keys[:20] if isinstance(k, str) and 0 < len(k) <= 64]
            if clean:
                await realtime.emit("ext_page", {"ext": ext_id, "keys": clean}, ["any"], durable=False)
    elif rest.startswith("trigger/"):
        if await events.wants(f"ext:{ext_id}"):
            await tasks.kick(
                "flows.dispatch", event={"type": "ext", "ext": ext_id, "key": rest[8:], "payload": payload}
            )


async def handle(m: aiomqtt.Message) -> None:
    t = m.topic.value
    raw = m.payload if isinstance(m.payload, (bytes, bytearray)) else str(m.payload or "").encode()
    text = raw.decode(errors="replace")
    payload = ingest.parse(raw)
    if t == DYN_RESP:
        for r in (payload or {}).get("responses", []) if isinstance(payload, dict) else []:
            corr = str(r.get("correlationData", "")).split(":")[0]
            if corr:
                await mqtt.deliver(corr, payload)
                break
        return
    if t.startswith("$SYS/"):
        await ingest.broker_stats(t, text)
        return
    if t == mqtt.RESP_TOPIC:
        corr = corr_of(m)
        if corr:
            await mqtt.deliver(corr, payload)
        return
    if t.startswith("hub/v1/core/"):
        return
    await mqttx.record(t, text, bool(m.retain), int(m.qos))
    base = settings.z2m_topic + "/"
    async with session() as s:
        if t.startswith(base):
            sub = t[len(base) :]
            if sub.startswith("bridge/response/") and isinstance(payload, dict) and payload.get("transaction"):
                await mqtt.deliver(str(payload["transaction"]), payload)
            await ingest.z2m(s, sub, payload)
        elif t.startswith("homeassistant/") and t.endswith("/config"):
            await ingest.ha_config(s, t, payload)
        elif t.startswith("hub/v1/ext/") and "/dev/" not in t:
            ext_id, _, rest = t[len("hub/v1/ext/") :].partition("/")
            await ext_message(ext_id, rest, m, payload)
        elif t.startswith("hub/v1/"):
            await ingest.hub(s, t, payload)
        targets = State.index.get(t)
        if targets:
            await ingest.mapped(s, t, payload, targets)
        await commit(s)
    if State.flows_mqtt and any(topic_matches_sub(f, t) for f in State.filters):
        await tasks.kick("flows.dispatch", event={"type": "mqtt", "topic": t, "payload": payload})


async def bootstrap() -> None:
    accounts = [
        (env("Z2M_MQTT_USER", "zigbee2mqtt"), env("Z2M_MQTT_PASSWORD"), ["zigbee2mqtt/#", "homeassistant/#"]),
        (env("MOCKS_MQTT_USER", "valo-mocks"), env("MOCKS_MQTT_PASSWORD"), ["#"]),
    ]
    for user, pw, prefixes in accounts:
        if not pw:
            continue
        try:
            await mqttx.ensure(user, pw, f"svc-{user}", mqttx.full_acl(*prefixes), reset=False)
            _log.info("account_ready", username=user)
        except ApplicationError as e:
            _log.error("account_failed", username=user, code=e.code)


async def loops() -> None:
    async def pump() -> None:
        while True:
            try:
                await tasks.pump()
            except Exception as e:
                _log.error("timer_pump_failed", error=str(e), exc_info=True)
            await asyncio.sleep(0.5)

    async def heartbeat() -> None:
        while True:
            await beat("mqtt", 30)
            await asyncio.sleep(10)

    async def watch() -> None:
        ps = kv().pubsub()
        await ps.subscribe("mqtt:index")
        async for msg in ps.listen():
            if msg.get("type") == "message":
                await asyncio.sleep(0.3)
                await refresh()
                if msg.get("data") == "resync":
                    await resync()

    await asyncio.gather(pump(), forever("mqtt_heartbeat", heartbeat, _log), forever("mqtt_watch", watch, _log))


async def resync() -> None:
    c = State.client
    if c is None:
        return
    await c.subscribe("#", qos=1)
    _log.info("mqtt_resync")


async def consume() -> None:
    while True:
        try:
            async with mqtt.client("valo-core-ingest", clean_start=True) as c:
                await c.subscribe("#", qos=1)
                await c.subscribe("$SYS/broker/#")
                await c.subscribe(DYN_RESP, qos=1)
                State.client = c
                _log.info("mqtt_connected", host=settings.mqtt_host)
                asyncio.get_running_loop().call_later(2, lambda: asyncio.ensure_future(bootstrap()))
                async for m in c.messages:
                    try:
                        await handle(m)
                    except Exception as e:
                        _log.error("message_failed", topic=m.topic.value, error=str(e), exc_info=True)
        except aiomqtt.MqttError as e:
            State.client = None
            _log.warning("mqtt_disconnected", error=str(e))
            await asyncio.sleep(3)


async def main() -> None:
    log.setup("mqtt")
    await tasks.broker.startup()
    await refresh()
    await asyncio.gather(consume(), loops())


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
