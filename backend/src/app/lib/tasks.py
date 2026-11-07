import json
import time
from typing import Any

from taskiq import InMemoryBroker, TaskiqMessage, TaskiqMiddleware, TaskiqResult, TaskiqScheduler
from taskiq.kicker import AsyncKicker
from taskiq.schedule_sources import LabelScheduleSource
from taskiq_aio_pika import AioPikaBroker

from app.lib import log
from app.lib.kv import kv
from app.lib.settings import settings

_log = log.get("tasks")


class LogMiddleware(TaskiqMiddleware):
    def post_execute(self, message: TaskiqMessage, result: TaskiqResult) -> None:
        if result.is_err:
            _log.error("task_failed", task=message.task_name, task_id=message.task_id, error=repr(result.error))


broker = (
    InMemoryBroker(await_inplace=True) if settings.app_env == "test" else AioPikaBroker(settings.rabbitmq_url)
).with_middlewares(LogMiddleware())
scheduler = TaskiqScheduler(broker, [LabelScheduleSource(broker)])


async def kick(task_name: str, /, **kwargs: Any) -> None:
    await AsyncKicker(task_name=task_name, broker=broker, labels={}).kiq(**kwargs)


async def later(key: str, delay: float, task_name: str, /, **kwargs: Any) -> None:
    pipe = kv().pipeline()
    pipe.hset("timers:data", key, json.dumps({"n": task_name, "k": kwargs}, default=str))
    pipe.zadd("timers", {key: time.time() + delay})
    await pipe.execute()


async def cancel(key: str) -> None:
    pipe = kv().pipeline()
    pipe.zrem("timers", key)
    pipe.hdel("timers:data", key)
    await pipe.execute()


async def pump(limit: int = 100) -> int:
    due = await kv().zrangebyscore("timers", "-inf", time.time(), start=0, num=limit)
    fired = 0
    for key in due:
        if not await kv().zrem("timers", key):
            continue
        raw = await kv().hget("timers:data", key)
        await kv().hdel("timers:data", key)
        if not raw:
            continue
        data = json.loads(raw)
        try:
            await kick(data["n"], **data["k"])
            fired += 1
        except Exception as e:
            _log.error("timer_kick_failed", key=key, task=data["n"], error=str(e))
    return fired
