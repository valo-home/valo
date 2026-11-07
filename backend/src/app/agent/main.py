"""Служба ИИ агента. Берет задания из очереди Redis, ведет цикл модель и инструменты, стримит ответ в chat:<id>."""

import asyncio
import json
import time
from typing import Any

from app.db.base import commit, session
from app.domain import assistant
from app.lib import llm, log, realtime
from app.lib.errors import ApplicationError
from app.lib.kv import BLOCK_MAX, beat, kv

_log = log.get("agent")
PARALLEL = 3
BUSY_TTL = 60
STEP_LABEL = "thinking"


class Stopped(Exception):
    pass


class Gone(Exception):
    pass


async def busy(chat: str) -> None:
    await kv().set(f"agent:busy:{chat}", 1, ex=BUSY_TTL)


async def stopped(chat: str) -> bool:
    return bool(await kv().exists(f"agent:stop:{chat}"))


async def step(chat: str, kind: str, tool: str = "") -> None:
    await realtime.emit("chat_step", {"chat": chat, "kind": kind, "tool": tool}, [f"chat:{chat}"], durable=False)


async def save(chat: str, role: str, content: str, data: dict[str, Any]) -> None:
    try:
        async with session() as s:
            await assistant.add(s, chat, role, content, data)
            await commit(s)
    except ApplicationError as e:
        if e.code == "chat_not_found":
            raise Gone from e
        raise


async def say_quiet(chat: str, role: str, content: str, data: dict[str, Any]) -> None:
    try:
        await save(chat, role, content, data)
    except Gone:
        _log.info("agent_chat_gone", chat=chat)


async def say_error(chat: str, code: str, detail: str = "") -> None:
    await say_quiet(chat, "assistant", "", {"error": code, "detail": detail[:300]})


async def model_turn(chat: str, cfg: llm.Config, msgs: list[dict[str, Any]], specs: list[dict[str, Any]]) -> llm.Reply:
    text, last = "", 0.0
    reply = llm.Reply()
    async for part in llm.stream(cfg, msgs, specs):
        if isinstance(part, llm.Reply):
            reply = part
            break
        text += part
        if time.monotonic() - last > 0.12:
            last = time.monotonic()
            await realtime.emit("chat_delta", {"chat": chat, "text": text}, [f"chat:{chat}"], durable=False)
            await busy(chat)
            if await stopped(chat):
                raise Stopped
    return reply


async def turn(job: dict[str, Any]) -> None:
    chat = str(job["chat"])
    tokens = 0
    await kv().delete(f"agent:stop:{chat}")
    await busy(chat)
    try:
        async with session() as s:
            p = await assistant.job_principal(s, job.get("principal") or {})
            row = await assistant.ai_row(s)
            cfg = assistant.config_of(row)
            system = await assistant.prompt(s, p) if p else None
            history = await assistant.history(s, chat)
            await commit(s)
        if p is None or system is None:
            await say_error(chat, "forbidden")
            return
        if cfg is None:
            await say_error(chat, "ai_disabled")
            return
        specs = assistant.tools.specs(p)
        msgs = [system, *history]
        for _ in range(row.max_steps):
            await step(chat, STEP_LABEL)
            reply = await model_turn(chat, cfg, msgs, specs)
            tokens += reply.usage.get("total", 0)
            calls = [{"id": c.id, "name": c.name, "arguments": c.arguments} for c in reply.calls]
            await save(chat, "assistant", reply.text, {"tool_calls": calls, "usage": reply.usage, "model": cfg.model})
            msgs.append(
                {
                    "role": "assistant",
                    "content": reply.text or None,
                    **(
                        {
                            "tool_calls": [
                                {
                                    "id": c["id"],
                                    "type": "function",
                                    "function": {"name": c["name"], "arguments": c["arguments"]},
                                }
                                for c in calls
                            ]
                        }
                        if calls
                        else {}
                    ),
                }
            )
            if not calls:
                break
            for c in calls:
                if await stopped(chat):
                    raise Stopped
                await step(chat, "tool", c["name"])
                await busy(chat)
                async with session() as s:
                    result, meta = await assistant.run_tool(s, p, chat, c["name"], c["arguments"])
                    try:
                        await assistant.add(
                            s, chat, "tool", result, {"tool_call_id": c["id"], "name": c["name"], **meta}
                        )
                    except ApplicationError as e:
                        raise Gone from e
                    await commit(s)
                msgs.append({"role": "tool", "tool_call_id": c["id"], "content": result})
        else:
            await say_error(chat, "ai_steps", str(row.max_steps))
    except Gone:
        _log.info("agent_chat_gone", chat=chat)
    except Stopped:
        await say_quiet(chat, "note", "stopped", {"kind": "stopped"})
    except llm.LlmError as e:
        await say_quiet(chat, "assistant", "", {"error": e.code, "detail": e.detail[:300]})
    except Exception as e:
        _log.error("agent_turn_failed", chat=chat, error=str(e), exc_info=True)
        await say_quiet(chat, "assistant", "", {"error": "internal"})
    finally:
        async with session() as s:
            await assistant.finish(s, chat, tokens)
            await commit(s)
        await step(chat, "done")
        await kv().delete(f"agent:busy:{chat}", f"agent:stop:{chat}")


async def worker(slots: asyncio.Semaphore) -> None:
    while True:
        try:
            item = await kv().brpop([assistant.JOBS], timeout=BLOCK_MAX)
        except Exception as e:
            _log.warning("agent_queue_failed", error=str(e))
            await asyncio.sleep(3)
            continue
        if not item:
            continue
        try:
            job = json.loads(item[1])
        except ValueError:
            _log.warning("agent_bad_job", raw=str(item[1])[:200])
            continue
        async with slots:
            _log.info("agent_turn", chat=job.get("chat"))
            try:
                await turn(job)
            except Exception as e:
                _log.error("agent_job_failed", chat=job.get("chat"), error=str(e), exc_info=True)


async def heartbeat() -> None:
    while True:
        try:
            await beat("agent", 30)
        except Exception as e:
            _log.warning("agent_beat_failed", error=str(e))
        await asyncio.sleep(10)


async def main() -> None:
    log.setup("agent")
    async with session() as s:
        n = await assistant.reset_stale(s)
        await commit(s)
    if n:
        _log.info("agent_reset_stale", chats=n)
    slots = asyncio.Semaphore(PARALLEL)
    await asyncio.gather(heartbeat(), *(worker(slots) for _ in range(PARALLEL)))


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
