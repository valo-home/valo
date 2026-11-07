"""ИИ ассистент: настройки модели, чаты пользователей, выполнение инструментов, подтверждение и отмена действий.

Ответы модели формирует служба agent (app.agent.main). API кладет задание в очередь Redis, агент ведет цикл
модель, инструменты, модель и рассылает поток ответа в комнату chat:<id>.
"""

import json
import uuid
from datetime import datetime
from typing import Any

import msgspec
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import after, now, savepoint
from app.db.models import AiSettings, Chat, ChatAction, ChatMessage, User
from app.domain import assistant_tools as tools
from app.domain import auth, events
from app.domain.common import UNSET, Principal, S, Unset, out
from app.lib import log, realtime, secretbox
from app.lib.errors import ApplicationError
from app.lib.kv import hit, kv
from app.lib.llm import Config
from app.lib.timeutil import zone

_log = log.get("assistant")
JOBS = "agent:jobs"
HISTORY = 40
MAX_TEXT = 8000


class AiSettingsOut(S):
    enabled: bool
    base_url: str
    model: str
    temperature: float
    max_steps: int
    daily_limit: int
    key_set: bool


class AiSettingsPatch(S):
    enabled: bool | Unset = UNSET
    base_url: str | Unset = UNSET
    model: str | Unset = UNSET
    api_key: str | Unset | None = UNSET
    temperature: float | Unset = UNSET
    max_steps: int | Unset = UNSET
    daily_limit: int | Unset = UNSET


class AiStatus(S):
    enabled: bool
    ready: bool
    model: str


class ChatOut(S):
    id: uuid.UUID
    title: str
    status: str
    tokens: int
    created_at: datetime
    updated_at: datetime


class MessageOut(S):
    id: int
    chat_id: uuid.UUID
    role: str
    content: str
    data: dict[str, Any]
    created_at: datetime


class ActionOut(S):
    id: uuid.UUID
    chat_id: uuid.UUID
    tool: str
    summary: str
    status: str
    result: dict[str, Any]
    can_undo: bool
    created_at: datetime
    done_at: datetime | None


class ChatIn(S):
    title: str = ""


class ChatPatch(S):
    title: str


class MessageIn(S):
    text: str


class ChatDetail(S):
    chat: ChatOut
    messages: list[MessageOut]
    actions: list[ActionOut]
    more: bool


async def ai_row(s: AsyncSession) -> AiSettings:
    row = await s.get(AiSettings, 1)
    if row is None:
        row = AiSettings(id=1)
        s.add(row)
        await s.flush()
    return row


def _settings_view(row: AiSettings) -> AiSettingsOut:
    return AiSettingsOut(
        enabled=row.enabled,
        base_url=row.base_url,
        model=row.model,
        temperature=row.temperature,
        max_steps=row.max_steps,
        daily_limit=row.daily_limit,
        key_set=bool(row.api_key),
    )


async def get_settings(s: AsyncSession, p: Principal) -> AiSettingsOut:
    p.need("admin")
    return _settings_view(await ai_row(s))


async def update_settings(s: AsyncSession, p: Principal, data: AiSettingsPatch) -> AiSettingsOut:
    p.need("admin")
    row = await ai_row(s)
    if not isinstance(data.base_url, Unset):
        url = data.base_url.strip().rstrip("/")
        if not url.startswith(("https://", "http://")) or len(url) > 255:
            raise ApplicationError("validation", 422, detail="baseUrl")
        row.base_url = url
    if not isinstance(data.model, Unset):
        if not data.model.strip() or len(data.model) > 160:
            raise ApplicationError("validation", 422, detail="model")
        row.model = data.model.strip()
    if not isinstance(data.temperature, Unset):
        if not 0 <= data.temperature <= 2:
            raise ApplicationError("validation", 422, detail="temperature")
        row.temperature = data.temperature
    if not isinstance(data.max_steps, Unset):
        if not 1 <= data.max_steps <= 30:
            raise ApplicationError("validation", 422, detail="maxSteps")
        row.max_steps = data.max_steps
    if not isinstance(data.daily_limit, Unset):
        if data.daily_limit < 0:
            raise ApplicationError("validation", 422, detail="dailyLimit")
        row.daily_limit = data.daily_limit
    if not isinstance(data.api_key, Unset):
        if data.api_key is None:
            row.api_key = ""
        elif data.api_key.strip():
            row.api_key = secretbox.seal(data.api_key.strip())
    if not isinstance(data.enabled, Unset):
        row.enabled = data.enabled
    await events.add(s, "ai.configured", actor=p.actor, params={"model": row.model, "enabled": row.enabled})
    return _settings_view(row)


def config_of(row: AiSettings) -> Config | None:
    key = secretbox.open_(row.api_key) if row.api_key else ""
    if not row.enabled or not key:
        return None
    return Config(base_url=row.base_url, api_key=str(key), model=row.model, temperature=row.temperature)


async def config(s: AsyncSession) -> Config | None:
    return config_of(await ai_row(s))


async def status(s: AsyncSession) -> AiStatus:
    row = await ai_row(s)
    return AiStatus(enabled=row.enabled, ready=config_of(row) is not None, model=row.model)


def _chat_view(c: Chat) -> ChatOut:
    return out(c, ChatOut)


def _msg_view(m: ChatMessage) -> MessageOut:
    return out(m, MessageOut)


def _action_view(a: ChatAction) -> ActionOut:
    return ActionOut(
        id=a.id,
        chat_id=a.chat_id,
        tool=a.tool,
        summary=a.summary,
        status=a.status,
        result=a.result,
        can_undo=a.status == "done" and bool(a.undo.get("ops")),
        created_at=a.created_at,
        done_at=a.done_at,
    )


def emit_chat(s: AsyncSession, c: Chat) -> None:
    snap, room = _chat_view(c), f"user:{c.user_id}"
    after(s, lambda: realtime.emit("chat", snap, [room]))


def emit_msg(s: AsyncSession, m: ChatMessage) -> None:
    snap, room = _msg_view(m), f"chat:{m.chat_id}"
    after(s, lambda: realtime.emit("chat_msg", snap, [room]))


def emit_action(s: AsyncSession, a: ChatAction) -> None:
    snap, room = _action_view(a), f"chat:{a.chat_id}"
    after(s, lambda: realtime.emit("chat_action", snap, [room]))


async def own(s: AsyncSession, p: Principal, chat_id: str, lock: bool = False) -> Chat:
    try:
        cid = uuid.UUID(str(chat_id))
    except ValueError as e:
        raise ApplicationError("chat_not_found", 404) from e
    c = await s.get(Chat, cid, with_for_update=lock, populate_existing=lock)
    if c is None or str(c.user_id) != p.id:
        raise ApplicationError("chat_not_found", 404)
    return c


async def listing(s: AsyncSession, p: Principal, limit: int = 50, before: str | None = None) -> list[ChatOut]:
    st = select(Chat).where(Chat.user_id == uuid.UUID(p.id)).order_by(Chat.updated_at.desc(), Chat.id.desc())
    if before:
        try:
            st = st.where(Chat.updated_at < datetime.fromisoformat(before))
        except ValueError as e:
            raise ApplicationError("validation", 422, detail="before") from e
    return [_chat_view(c) for c in (await s.scalars(st.limit(max(1, min(limit, 200))))).all()]


async def create(s: AsyncSession, p: Principal, data: ChatIn) -> ChatOut:
    if p.id == "system" or p.scope == "read":
        raise ApplicationError("forbidden", 403)
    c = Chat(user_id=uuid.UUID(p.id), title=data.title.strip()[:160])
    s.add(c)
    await s.flush()
    emit_chat(s, c)
    return _chat_view(c)


async def detail(s: AsyncSession, p: Principal, chat_id: str, before: int | None = None, limit: int = 60) -> ChatDetail:
    c = await own(s, p, chat_id)
    limit = max(1, min(limit, 200))
    st = select(ChatMessage).where(ChatMessage.chat_id == c.id).order_by(ChatMessage.id.desc()).limit(limit + 1)
    if before:
        st = st.where(ChatMessage.id < before)
    rows = list((await s.scalars(st)).all())
    acts = (await s.scalars(select(ChatAction).where(ChatAction.chat_id == c.id).order_by(ChatAction.created_at))).all()
    return ChatDetail(
        chat=_chat_view(c),
        messages=[_msg_view(m) for m in reversed(rows[:limit])],
        actions=[_action_view(a) for a in acts],
        more=len(rows) > limit,
    )


async def rename(s: AsyncSession, p: Principal, chat_id: str, data: ChatPatch) -> ChatOut:
    c = await own(s, p, chat_id)
    c.title = data.title.strip()[:160]
    emit_chat(s, c)
    return _chat_view(c)


async def remove(s: AsyncSession, p: Principal, chat_id: str) -> None:
    c = await own(s, p, chat_id)
    room, cid = f"user:{c.user_id}", str(c.id)
    await kv().set(f"agent:stop:{cid}", 1, ex=600)
    await s.delete(c)
    after(s, lambda: realtime.emit("chat_gone", {"id": cid}, [room]))


def title_of(text: str) -> str:
    line = " ".join(text.split())
    return line if len(line) <= 60 else line[:57].rsplit(" ", 1)[0] + "..."


async def post(s: AsyncSession, p: Principal, chat_id: str, data: MessageIn) -> MessageOut:
    c = await own(s, p, chat_id, lock=True)
    if p.scope == "read":
        raise ApplicationError("forbidden", 403)
    text = data.text.strip()
    if not text or len(text) > MAX_TEXT:
        raise ApplicationError("validation", 422, detail="text")
    row = await ai_row(s)
    if config_of(row) is None:
        raise ApplicationError("ai_disabled", 409)
    if c.status == "running" and await kv().exists(f"agent:busy:{c.id}"):
        raise ApplicationError("chat_busy", 409)
    if not await hit(f"chat:rate:{p.id}", 20, 60):
        raise ApplicationError("rate_limited", 429)
    if row.daily_limit:
        h = await events.home(s)
        start = datetime.now(zone(h.timezone)).replace(hour=0, minute=0, second=0, microsecond=0)
        used = await s.scalar(
            select(func.count())
            .select_from(ChatMessage)
            .join(Chat, Chat.id == ChatMessage.chat_id)
            .where(Chat.user_id == c.user_id, ChatMessage.role == "user", ChatMessage.created_at >= start)
        )
        if (used or 0) >= row.daily_limit:
            raise ApplicationError("ai_limit", 429, limit=row.daily_limit)
    m = ChatMessage(chat_id=c.id, role="user", content=text, data={})
    s.add(m)
    if not c.title:
        c.title = title_of(text)
    c.status, c.updated_at = "running", now()
    await s.flush()
    job = json.dumps(
        {
            "chat": str(c.id),
            "principal": {"id": p.id, "role": p.role, "rooms": p.rooms, "scope": p.scope},
            "message": m.id,
        }
    )
    emit_msg(s, m)
    emit_chat(s, c)
    after(s, lambda: kv().lpush(JOBS, job))
    return _msg_view(m)


async def stop(s: AsyncSession, p: Principal, chat_id: str) -> ChatOut:
    c = await own(s, p, chat_id, lock=True)
    await kv().set(f"agent:stop:{c.id}", 1, ex=600)
    if c.status == "running" and not await kv().exists(f"agent:busy:{c.id}"):
        c.status, c.updated_at = "idle", now()
        emit_chat(s, c)
    return _chat_view(c)


async def job_principal(s: AsyncSession, raw: dict[str, Any]) -> Principal | None:
    """Права для задания агента: текущая роль пользователя, ограничения токена из задания сохраняются."""
    try:
        u = await s.get(User, uuid.UUID(str(raw.get("id"))))
    except ValueError:
        return None
    if u is None or not u.active:
        return None
    p = auth.principal(u, scope=str(raw.get("scope") or "full"), rooms=list(raw.get("rooms") or []) or None)
    return p


async def lang_of(s: AsyncSession, p: Principal) -> str:
    u = await s.get(User, uuid.UUID(p.id))
    h = await events.home(s)
    return (u.lang if u and u.lang else None) or str((h.settings or {}).get("lang") or "uk")


async def prompt(s: AsyncSession, p: Principal) -> dict[str, Any]:
    h = await events.home(s)
    lang = await lang_of(s, p)
    local = datetime.now(zone(h.timezone)).strftime("%Y-%m-%d %H:%M %A")
    return {"role": "system", "content": tools.system_prompt(h.name, lang, p, local)}


def to_llm(msgs: list[ChatMessage]) -> list[dict[str, Any]]:
    out_: list[dict[str, Any]] = []
    for m in msgs:
        if m.role == "user":
            out_.append({"role": "user", "content": m.content})
        elif m.role == "note":
            out_.append({"role": "user", "content": f"[Valo] {m.content}"})
        elif m.role == "assistant":
            item: dict[str, Any] = {"role": "assistant", "content": m.content or None}
            calls = m.data.get("tool_calls") or []
            if calls:
                item["tool_calls"] = [
                    {"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": c["arguments"]}}
                    for c in calls
                ]
            if item["content"] is None and not calls:
                continue
            out_.append(item)
        elif m.role == "tool":
            out_.append({"role": "tool", "tool_call_id": m.data.get("tool_call_id", ""), "content": m.content})
    known = {c["id"] for x in out_ if x["role"] == "assistant" for c in x.get("tool_calls", [])}
    return [x for x in out_ if x["role"] != "tool" or x["tool_call_id"] in known]


async def history(s: AsyncSession, chat_id: str) -> list[dict[str, Any]]:
    rows = list(
        (
            await s.scalars(
                select(ChatMessage)
                .where(ChatMessage.chat_id == uuid.UUID(chat_id))
                .order_by(ChatMessage.id.desc())
                .limit(HISTORY)
            )
        ).all()
    )
    rows.reverse()
    while rows and rows[0].role not in ("user", "note"):
        rows.pop(0)
    return to_llm(rows)


async def add(
    s: AsyncSession, chat_id: str, role: str, content: str, data: dict[str, Any] | None = None
) -> ChatMessage:
    if await s.get(Chat, uuid.UUID(chat_id)) is None:
        raise ApplicationError("chat_not_found", 404)
    m = ChatMessage(chat_id=uuid.UUID(chat_id), role=role, content=content, data=data or {})
    s.add(m)
    await s.flush()
    emit_msg(s, m)
    return m


async def finish(s: AsyncSession, chat_id: str, tokens: int) -> None:
    c = await s.get(Chat, uuid.UUID(chat_id), with_for_update=True, populate_existing=True)
    if c is None:
        return
    c.status, c.tokens, c.updated_at = "idle", c.tokens + tokens, now()
    emit_chat(s, c)


async def reset_stale(s: AsyncSession) -> int:
    n = 0
    for c in (await s.scalars(select(Chat).where(Chat.status == "running"))).all():
        if not await kv().exists(f"agent:busy:{c.id}"):
            c.status, c.updated_at = "idle", now()
            emit_chat(s, c)
            n += 1
    return n


def plain(v: Any) -> Any:
    return msgspec.to_builtins(v, enc_hook=str)


def _dump(v: Any) -> str:
    text = json.dumps(plain(v), ensure_ascii=False, default=str)
    return text if len(text) <= tools.MAX_RESULT else text[: tools.MAX_RESULT] + "...(truncated)"


async def run_tool(s: AsyncSession, p: Principal, chat_id: str, name: str, raw: str) -> tuple[str, dict[str, Any]]:
    """Выполнить вызов инструмента модели. Возвращает текст результата для модели и метаданные для сообщения."""
    t = tools.BY_NAME.get(name)
    if t is None or not tools.allowed(t, p):
        return _dump({"error": "unknown_tool", "tool": name}), {"ok": False}
    try:
        args = json.loads(raw or "{}")
        if not isinstance(args, dict):
            raise ValueError("arguments must be an object")
    except ValueError as e:
        return _dump({"error": "bad_arguments", "detail": str(e)}), {"ok": False}
    ctx = tools.Ctx(s=s, p=p, lang=await lang_of(s, p))
    try:
        async with savepoint(s):
            res = await t.fn(ctx, args)
            if t.mode == "confirm":
                a = ChatAction(
                    chat_id=uuid.UUID(chat_id), tool=name, args=args, summary=ctx.summary[:400], status="pending"
                )
                s.add(a)
                await s.flush()
                emit_action(s, a)
                return _dump({"status": "waiting_for_user", "action_id": str(a.id), "summary": a.summary}), {
                    "ok": True,
                    "action": str(a.id),
                }
            if t.mode == "write":
                a = ChatAction(
                    chat_id=uuid.UUID(chat_id),
                    tool=name,
                    args=args,
                    summary=ctx.summary[:400],
                    status="done",
                    result={"value": res},
                    undo={"ops": ctx.undo},
                    done_at=now(),
                )
                s.add(a)
                await s.flush()
                emit_action(s, a)
                return _dump({"ok": True, "result": res, "action_id": str(a.id)}), {"ok": True, "action": str(a.id)}
    except ApplicationError as e:
        _log.info("assistant_tool_failed", tool=name, code=e.code)
        return _dump({"error": e.code, "params": e.params}), {"ok": False, "error": e.code}
    except (KeyError, TypeError, ValueError) as e:
        _log.warning("assistant_tool_bad_arguments", tool=name, error=str(e), exc_info=True)
        return _dump({"error": "bad_arguments", "detail": str(e)}), {"ok": False}
    return _dump(res), {"ok": True}


async def _action(s: AsyncSession, p: Principal, chat_id: str, action_id: str) -> tuple[Chat, ChatAction]:
    c = await own(s, p, chat_id, lock=True)
    try:
        a = await s.get(ChatAction, uuid.UUID(action_id))
    except ValueError as e:
        raise ApplicationError("action_not_found", 404) from e
    if a is None or a.chat_id != c.id:
        raise ApplicationError("action_not_found", 404)
    return c, a


async def _note(s: AsyncSession, c: Chat, text: str, kind: str) -> None:
    await add(s, str(c.id), "note", text, {"kind": kind})
    c.updated_at = now()
    emit_chat(s, c)


async def confirm(s: AsyncSession, p: Principal, chat_id: str, action_id: str) -> ActionOut:
    c, a = await _action(s, p, chat_id, action_id)
    if a.status != "pending":
        raise ApplicationError("action_done", 409)
    t = tools.BY_NAME.get(a.tool)
    if t is None or not tools.allowed(t, p):
        raise ApplicationError("forbidden", 403)
    ctx = tools.Ctx(s=s, p=p, lang=await lang_of(s, p))
    try:
        async with savepoint(s):
            run = await t.fn(ctx, a.args)
            res = await run()
        value = plain(res)
        a.status, a.result = "done", {"value": value if len(_dump(value)) < tools.MAX_RESULT else "ok"}
        await _note(s, c, f"User confirmed: {a.summary}. Done", "confirmed")
    except ApplicationError as e:
        a.status, a.result = "failed", {"error": e.code, "params": e.params}
        await _note(s, c, f"User confirmed: {a.summary}. Failed: {e.code}", "failed")
    a.done_at = now()
    emit_action(s, a)
    return _action_view(a)


async def reject(s: AsyncSession, p: Principal, chat_id: str, action_id: str) -> ActionOut:
    c, a = await _action(s, p, chat_id, action_id)
    if a.status != "pending":
        raise ApplicationError("action_done", 409)
    a.status, a.done_at = "rejected", now()
    await _note(s, c, f"User declined: {a.summary}", "rejected")
    emit_action(s, a)
    return _action_view(a)


async def revert(s: AsyncSession, p: Principal, chat_id: str, action_id: str) -> ActionOut:
    c, a = await _action(s, p, chat_id, action_id)
    if a.status != "done" or not a.undo.get("ops"):
        raise ApplicationError("action_done", 409)
    async with savepoint(s):
        await tools.undo(s, p, a.undo["ops"])
    a.status = "undone"
    await _note(s, c, f"User undid: {a.summary}", "undone")
    emit_action(s, a)
    return _action_view(a)
