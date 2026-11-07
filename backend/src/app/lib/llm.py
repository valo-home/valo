"""Клиент языковой модели через OpenAI SDK (OpenRouter и совместимые API). Поток текста и вызовов инструментов."""

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from openai import APIError, APIStatusError, AsyncOpenAI

from app.lib import log

_log = log.get("llm")
HEADERS = {"HTTP-Referer": "https://valo.local", "X-Title": "Valo"}


@dataclass
class Config:
    base_url: str
    api_key: str
    model: str
    temperature: float = 0.3


@dataclass
class Call:
    id: str
    name: str
    arguments: str = ""


@dataclass
class Reply:
    text: str = ""
    calls: list[Call] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)
    finish: str = ""


class LlmError(Exception):
    def __init__(self, code: str, detail: str = "", status: int | None = None) -> None:
        super().__init__(detail or code)
        self.code, self.detail, self.status = code, detail, status


def client(cfg: Config) -> AsyncOpenAI:
    return AsyncOpenAI(base_url=cfg.base_url, api_key=cfg.api_key, default_headers=HEADERS, timeout=120, max_retries=2)


def _error(e: Exception) -> LlmError:
    if isinstance(e, APIStatusError):
        code = {401: "llm_auth", 402: "llm_credits", 403: "llm_auth", 404: "llm_model", 429: "llm_rate"}.get(
            e.status_code, "llm_failed"
        )
        body = e.body if isinstance(e.body, dict) else {}
        detail = str((body.get("error") or {}).get("message") or body.get("message") or e.message)[:300]
        return LlmError(code, detail, e.status_code)
    return LlmError("llm_failed", str(e)[:300])


async def stream(
    cfg: Config, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
) -> AsyncIterator[str | Reply]:
    """Отдает куски текста по мере генерации, последним элементом полный Reply."""
    reply = Reply()
    calls: dict[int, Call] = {}
    try:
        resp = await client(cfg).chat.completions.create(
            model=cfg.model,
            messages=messages,
            tools=tools or None,
            temperature=cfg.temperature,
            stream=True,
            stream_options={"include_usage": True},
        )
        async for chunk in resp:
            if chunk.usage:
                reply.usage = {
                    "prompt": chunk.usage.prompt_tokens or 0,
                    "completion": chunk.usage.completion_tokens or 0,
                    "total": chunk.usage.total_tokens or 0,
                }
            for ch in chunk.choices or []:
                d = ch.delta
                if d and d.content:
                    reply.text += d.content
                    yield d.content
                for tc in (d.tool_calls if d else None) or []:
                    c = calls.setdefault(tc.index, Call(id="", name=""))
                    if tc.id:
                        c.id = tc.id
                    if tc.function and tc.function.name:
                        c.name += tc.function.name
                    if tc.function and tc.function.arguments:
                        c.arguments += tc.function.arguments
                if ch.finish_reason:
                    reply.finish = ch.finish_reason
    except (APIError, OSError) as e:
        err = _error(e)
        _log.warning("llm_call_failed", code=err.code, status=err.status, detail=err.detail, model=cfg.model)
        raise err from e
    reply.calls = [c for _, c in sorted(calls.items()) if c.name]
    for i, c in enumerate(reply.calls):
        if not c.id:
            c.id = f"call_{i}"
    yield reply


async def models(cfg: Config) -> list[dict[str, Any]]:
    try:
        page = await client(cfg).models.list()
    except (APIError, OSError) as e:
        raise _error(e) from e
    out = []
    for m in page.data:
        extra = getattr(m, "model_extra", None) or {}
        out.append({"id": m.id, "name": extra.get("name") or m.id, "context": extra.get("context_length")})
    return sorted(out, key=lambda x: x["id"])
