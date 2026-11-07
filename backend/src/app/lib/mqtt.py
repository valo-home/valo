import asyncio
import json
import time
import uuid
from typing import Any

import aiomqtt
import msgspec
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.properties import Properties

from app.lib import log
from app.lib.errors import ApplicationError
from app.lib.kv import kv
from app.lib.settings import settings

RESP_TOPIC = "hub/v1/core/resp"
_log = log.get("mqtt_client")
_pub: aiomqtt.Client | None = None
_lock = asyncio.Lock()


def client(identifier: str | None = None, **kw) -> aiomqtt.Client:
    return aiomqtt.Client(
        settings.mqtt_host,
        settings.mqtt_port,
        username=settings.mqtt_user or None,
        password=settings.mqtt_password or None,
        identifier=identifier or f"valo-{uuid.uuid4().hex[:10]}",
        protocol=aiomqtt.ProtocolVersion.V5,
        **kw,
    )


def props(
    response_topic: str | None = None, correlation: str | None = None, expiry: int | None = None
) -> Properties | None:
    if not (response_topic or correlation or expiry):
        return None
    p = Properties(PacketTypes.PUBLISH)
    if response_topic:
        p.ResponseTopic = response_topic
    if correlation:
        p.CorrelationData = correlation.encode()
    if expiry:
        p.MessageExpiryInterval = expiry
    return p


def encode(payload: Any) -> str | bytes | None:
    if payload is None or isinstance(payload, (str, bytes, bytearray)):
        return payload
    return msgspec.json.encode(payload)


def decode(payload: Any) -> Any:
    raw = payload.decode() if isinstance(payload, (bytes, bytearray)) else payload
    if not isinstance(raw, str):
        return raw
    try:
        return json.loads(raw)
    except ValueError:
        return raw


async def _connected() -> aiomqtt.Client:
    global _pub
    async with _lock:
        if _pub is None:
            c = client()
            try:
                await c.__aenter__()
            except aiomqtt.MqttError as e:
                _log.error("mqtt_connect_failed", error=str(e))
                raise ApplicationError("mqtt_unavailable", 503) from e
            _pub = c
        return _pub


async def publish(
    topic: str, payload: Any = None, qos: int = 0, retain: bool = False, properties: Properties | None = None
) -> None:
    global _pub
    for attempt in (1, 2):
        c = await _connected()
        try:
            await c.publish(topic, encode(payload), qos=qos, retain=retain, properties=properties)
            return
        except aiomqtt.MqttError as e:
            _log.warning("mqtt_publish_failed", topic=topic, attempt=attempt, error=str(e))
            async with _lock:
                _pub = None
    raise ApplicationError("mqtt_unavailable", 503)


async def wait(key: str, timeout: float) -> Any:
    end = time.monotonic() + timeout
    while (left := end - time.monotonic()) > 0:
        got = await kv().blpop([f"mqtt:resp:{key}"], timeout=min(left, 4))
        if got:
            return json.loads(got[1])
    raise ApplicationError("mqtt_timeout", 504)


async def request(
    topic: str, payload: Any, key: str, timeout: float = 10.0, properties: Properties | None = None
) -> Any:
    await kv().delete(f"mqtt:resp:{key}")
    await publish(topic, payload, qos=1, properties=properties)
    return await wait(key, timeout)


async def deliver(key: str, payload: Any) -> None:
    k = f"mqtt:resp:{key}"
    await kv().rpush(k, json.dumps(payload, default=str))
    await kv().expire(k, 120)


async def close() -> None:
    global _pub
    if _pub is not None:
        try:
            await _pub.__aexit__(None, None, None)
        except Exception:
            pass
        _pub = None
