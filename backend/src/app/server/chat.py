from typing import Any

from litestar import Router, delete, get, post
from litestar import patch as patch_route
from litestar.di import NamedDependency, Provide
from litestar.params import FromPath, FromQuery, JSONBody
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import assistant
from app.domain.common import Principal
from app.lib import llm, secretbox
from app.lib.errors import ApplicationError
from app.server.base import authed, done, principal

Db = NamedDependency[AsyncSession]
P = NamedDependency[Principal]


@get("/ai/status")
async def ai_status(db_session: Db) -> assistant.AiStatus:
    return await assistant.status(db_session)


@get("/ai/settings")
async def ai_settings(db_session: Db, p: P) -> assistant.AiSettingsOut:
    return await assistant.get_settings(db_session, p)


@patch_route("/ai/settings")
async def ai_settings_update(
    db_session: Db, p: P, data: JSONBody[assistant.AiSettingsPatch]
) -> assistant.AiSettingsOut:
    return await done(db_session, await assistant.update_settings(db_session, p, data))


async def _cfg(s: AsyncSession, p: Principal) -> llm.Config:
    p.need("admin")
    row = await assistant.ai_row(s)
    key = secretbox.open_(row.api_key) if row.api_key else ""
    if not key:
        raise ApplicationError("ai_no_key", 409)
    return llm.Config(base_url=row.base_url, api_key=str(key), model=row.model, temperature=row.temperature)


def _llm_error(e: llm.LlmError) -> ApplicationError:
    return ApplicationError(e.code, 502, detail=e.detail)


@get("/ai/models")
async def ai_models(db_session: Db, p: P) -> list[dict[str, Any]]:
    cfg = await _cfg(db_session, p)
    try:
        return await llm.models(cfg)
    except llm.LlmError as e:
        raise _llm_error(e) from e


@post("/ai/test", status_code=200)
async def ai_test(db_session: Db, p: P) -> dict[str, Any]:
    cfg = await _cfg(db_session, p)
    text, usage = "", {}
    try:
        async for part in llm.stream(cfg, [{"role": "user", "content": "Reply with the single word OK"}]):
            if isinstance(part, llm.Reply):
                text, usage = part.text, part.usage
    except llm.LlmError as e:
        raise _llm_error(e) from e
    return {"ok": True, "model": cfg.model, "reply": text.strip()[:100], "usage": usage}


@get("/chats")
async def chats(
    db_session: Db, p: P, before: FromQuery[str | None] = None, limit: FromQuery[int] = 50
) -> list[assistant.ChatOut]:
    return await assistant.listing(db_session, p, limit, before)


@post("/chats")
async def chat_create(db_session: Db, p: P, data: JSONBody[assistant.ChatIn]) -> assistant.ChatOut:
    return await done(db_session, await assistant.create(db_session, p, data))


@get("/chats/{chat_id:str}")
async def chat_detail(
    db_session: Db, p: P, chat_id: FromPath[str], before: FromQuery[int | None] = None, limit: FromQuery[int] = 60
) -> assistant.ChatDetail:
    return await assistant.detail(db_session, p, chat_id, before, limit)


@patch_route("/chats/{chat_id:str}")
async def chat_rename(
    db_session: Db, p: P, chat_id: FromPath[str], data: JSONBody[assistant.ChatPatch]
) -> assistant.ChatOut:
    return await done(db_session, await assistant.rename(db_session, p, chat_id, data))


@delete("/chats/{chat_id:str}")
async def chat_delete(db_session: Db, p: P, chat_id: FromPath[str]) -> None:
    await assistant.remove(db_session, p, chat_id)
    await done(db_session)


@post("/chats/{chat_id:str}/messages", status_code=202)
async def chat_post(
    db_session: Db, p: P, chat_id: FromPath[str], data: JSONBody[assistant.MessageIn]
) -> assistant.MessageOut:
    return await done(db_session, await assistant.post(db_session, p, chat_id, data))


@post("/chats/{chat_id:str}/stop", status_code=200)
async def chat_stop(db_session: Db, p: P, chat_id: FromPath[str]) -> assistant.ChatOut:
    return await done(db_session, await assistant.stop(db_session, p, chat_id))


@post("/chats/{chat_id:str}/actions/{action_id:str}/{op:str}", status_code=200)
async def chat_action(
    db_session: Db, p: P, chat_id: FromPath[str], action_id: FromPath[str], op: FromPath[str]
) -> assistant.ActionOut:
    fn = {"confirm": assistant.confirm, "reject": assistant.reject, "undo": assistant.revert}.get(op)
    if fn is None:
        raise ApplicationError("not_found", 404)
    return await done(db_session, await fn(db_session, p, chat_id, action_id))


chat = Router(
    "/api/v1",
    dependencies={"p": Provide(principal)},
    guards=[authed],
    route_handlers=[
        ai_status,
        ai_settings,
        ai_settings_update,
        ai_models,
        ai_test,
        chats,
        chat_create,
        chat_detail,
        chat_rename,
        chat_delete,
        chat_post,
        chat_stop,
        chat_action,
    ],
)
