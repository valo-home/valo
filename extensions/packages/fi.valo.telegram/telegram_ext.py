import asyncio
import base64
import json
import time
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from tglogic import (
    SOURCES,
    Actions,
    Dedupe,
    allowed,
    buttons,
    caption,
    clip_ready,
    delivery_hint,
    devices_text,
    fallback_text,
    flow_media,
    media_link,
    multipart,
    parse_ids,
    parse_recipients,
    pick,
    quiet,
    rejected_recipients,
    status_text,
    tr,
    upload_method,
)
from valo_sdk import Extension

ext = Extension()
state: dict[str, Any] = {"tz": ZoneInfo("Europe/Helsinki"), "lang": "uk", "home": "Valo", "offset": 0, "fail_at": 0.0}
dedupe = Dedupe()
actions = Actions(ext.data / "actions.json")
CHATS = ext.data / "chats.json"


def token() -> str:
    return str(ext.settings.get("token") or "")


def recipients_text() -> str:
    return str(ext.settings.get("recipients") or ext.settings.get("chats") or "")


def recipients() -> list[tuple[str, str]]:
    return parse_recipients(recipients_text())


def admins() -> set[str]:
    return parse_ids(str(ext.settings.get("admins") or ""))


def api(method: str, payload: dict[str, Any], timeout: float = 15) -> Any:
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token()}/{method}",
        data=json.dumps(payload).encode(),
        headers={"content-type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            desc = json.loads(e.read()).get("description")
        except ValueError:
            desc = None
        raise RuntimeError(f"{e.code} {desc or e.reason}") from e
    if not body.get("ok"):
        raise RuntimeError(str(body.get("description") or body))
    return body.get("result")


async def call(method: str, payload: dict[str, Any], timeout: float = 15) -> Any:
    return await asyncio.to_thread(api, method, payload, timeout)


def api_file(method: str, fields: dict[str, str], name: str, filename: str, content: bytes, ctype: str) -> Any:
    body, kind = multipart(fields, name, filename, content, ctype)
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token()}/{method}", data=body, headers={"content-type": kind}
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            res = json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            desc = json.loads(e.read()).get("description")
        except ValueError:
            desc = None
        raise RuntimeError(f"{e.code} {desc or e.reason}") from e
    if not res.get("ok"):
        raise RuntimeError(str(res.get("description") or res))
    return res.get("result")


def seen_chats() -> dict[str, Any]:
    try:
        return json.loads(CHATS.read_text("utf-8"))
    except OSError, ValueError:
        return {}


def remember_chat(chat: dict[str, Any], user: dict[str, Any] | None) -> None:
    chats = seen_chats()
    title = chat.get("title") or " ".join(x for x in (chat.get("first_name"), chat.get("last_name")) if x)
    chats[str(chat["id"])] = {
        "title": title or chat.get("username") or str(chat["id"]),
        "type": chat.get("type"),
        "user": (user or {}).get("id"),
        "last": time.time(),
    }
    CHATS.parent.mkdir(parents=True, exist_ok=True)
    CHATS.write_text(json.dumps(chats, ensure_ascii=False), "utf-8")


async def report_failure(error: str) -> None:
    ext.log.error("telegram delivery failed: %s", error)
    if time.time() - state["fail_at"] > 3600:
        state["fail_at"] = time.time()
        try:
            text = " ".join(x for x in (f"Telegram: {error}.", delivery_hint(state["lang"], error)) if x)
            await ext.call("notify", {"key": "delivery", "level": "warn", "text": text})
        except Exception as e:
            ext.log.warning("core notify failed: %s", e)


async def send(
    text: str,
    to: str = "",
    level: str = "info",
    silent: bool = False,
    btns: list[tuple[str, str, dict[str, Any]]] | None = None,
    once: bool = True,
) -> dict[str, Any]:
    chats, unknown = pick(recipients(), to)
    if unknown:
        ext.log.warning("unknown recipients: %s", ", ".join(unknown))
    if not text.strip():
        return {"sent": 0, "skipped": "empty"}
    if not token() or not chats:
        ext.log.info("not configured, message not sent: %s", text[:200])
        return {"sent": 0, "skipped": "not_configured", "unknown": unknown}
    key = f"{','.join(chats)}|{text}"
    if once and not dedupe.allow(key, float(ext.settings.get("dedupe") or 0)):
        ext.log.info("duplicate suppressed: %s", text[:120])
        return {"sent": 0, "skipped": "duplicate"}
    silent = silent or (quiet(str(ext.settings.get("quiet") or ""), datetime.now(state["tz"])) and level != "crit")
    payload: dict[str, Any] = {"text": text[:4000], "disable_notification": silent}
    if btns:
        payload["reply_markup"] = {
            "inline_keyboard": [
                [{"text": label, "callback_data": f"a:{actions.add(dev, vals, label)}"} for label, dev, vals in btns]
            ]
        }
    sent, errors = 0, []
    for chat in chats:
        try:
            await call("sendMessage", {**payload, "chat_id": chat})
            sent += 1
        except Exception as e:
            errors.append(f"{chat}: {e}")
    if errors:
        await report_failure("; ".join(errors)[:300])
    return {"sent": sent, "failed": len(errors), "silent": silent, "unknown": unknown}


@ext.on_start
async def start() -> None:
    try:
        home = await ext.call("home")
        state.update(tz=ZoneInfo(home.get("timezone") or "Europe/Helsinki"), lang=home.get("lang") or "uk")
        state["home"] = home.get("name") or "Valo"
    except Exception as e:
        ext.log.warning("home info unavailable: %s", e)
    ext.log.info(
        "recipients %s, admins %s, token %s", len(recipients()), len(admins()), "set" if token() else "missing"
    )
    if bad := rejected_recipients(recipients_text()):
        ext.log.warning("recipients not accepted, a numeric chat id is needed: %s", ", ".join(bad))


@ext.service("notify")
async def notify(params: dict) -> dict:
    return await send(str(params.get("text") or ""), str(params.get("to") or ""), str(params.get("level") or "info"))


@ext.block("message")
async def message(params: dict, tok: dict, dry: bool) -> dict:
    text, to = str(params.get("text") or ""), str(params.get("to") or "")
    btns = buttons(params, tok)
    if dry:
        chats, unknown = pick(recipients(), to)
        trace = {"text": text, "count": len(chats), "buttons": len(btns)}
        if unknown:
            trace["unknown"] = ", ".join(unknown)
        return {"outs": [[0]], "trace": {"s": "skip", "m": "dry_ext", "p": trace}}
    res = await send(text, to, silent=bool(params.get("silent")), btns=btns)
    status = "ok" if res.get("sent") else "skip" if res.get("skipped") else "fail"
    trace = {"text": text, "count": res.get("sent", 0)}
    if res.get("skipped"):
        trace["reason"] = res["skipped"]
    return {"outs": [[0]], "trace": {"s": status, "m": "ext_sent", "p": trace}}


CLIP_WAIT = 90


async def camera_of(params: dict[str, Any], tok: dict[str, Any]) -> tuple[str, str]:
    want = str(params.get("camera") or "")
    if not want and tok.get("camera"):
        want = str(tok["camera"])
    want = want or str(tok.get("d") or "")
    if not want:
        return "", ""
    for c in await ext.cameras() or []:
        if want in (c.get("id"), c.get("deviceId")):
            return str(c["id"]), str(c.get("name") or c["id"])
    return "", ""


async def wait_clip(cid: str, job: dict[str, Any], seconds: int) -> dict[str, Any] | None:
    since = float(job.get("at") or time.time())
    await asyncio.sleep(seconds + 3)
    deadline = time.monotonic() + CLIP_WAIT
    while time.monotonic() < deadline:
        items = await ext.call("media.list", {"camera": cid, "kind": "video", "limit": 10})
        found = clip_ready(items, since, f"ext:{ext.id}")
        if found:
            return found
        await asyncio.sleep(3)
    return None


async def deliver(chats: list[str], text: str, mid: str, silent: bool) -> dict[str, Any]:
    lang = state["lang"]
    link = media_link(str(ext.settings.get("link") or ""), mid)
    sent, errors = 0, []
    try:
        rec = await ext.media(mid)
    except Exception as e:
        ext.log.error("media %s not readable: %s", mid, e)
        rec = None
    how = upload_method(str(rec.get("kind")), int(rec.get("size") or 0)) if rec and rec.get("data") else None
    if rec is None:
        note = tr(lang, "not_sent_media", error="media unavailable")
    elif how is None:
        note = tr(lang, "too_big", size=round(int(rec.get("size") or 0) / 1024**2, 1))
        ext.log.warning("media %s %s of %s bytes is too large for Telegram", mid, rec.get("kind"), rec.get("size"))
    else:
        note = ""
    if how and rec:
        method, field = how
        content = base64.b64decode(rec["data"])
        photo = field == "photo"
        name = f"valo-{mid[:8]}.{'jpg' if photo else 'mp4'}"
        for chat in chats:
            fields = {"chat_id": chat, "caption": caption(text), "disable_notification": str(silent).lower()}
            if not photo:
                fields["supports_streaming"] = "true"
                if rec.get("duration"):
                    fields["duration"] = str(int(float(rec["duration"])))
            try:
                await asyncio.to_thread(
                    api_file, method, fields, field, name, content, "image/jpeg" if photo else "video/mp4"
                )
                sent += 1
            except Exception as e:
                errors.append(f"{chat}: {e}")
        if errors and not sent:
            note = tr(lang, "not_sent_media", error=errors[0].split(": ", 1)[-1][:120])
    if note:
        body = fallback_text(lang, text, note, link)
        for chat in chats if not sent else []:
            try:
                await call("sendMessage", {"chat_id": chat, "text": body, "disable_notification": silent})
            except Exception as e:
                errors.append(f"{chat}: {e}")
    if errors:
        await report_failure("; ".join(errors)[:300])
    return {"sent": sent, "failed": len(errors), "fallback": bool(note)}


async def send_media(
    chats: list[str], text: str, source: str, cid: str, mid: str | None, seconds: int, silent: bool
) -> None:
    try:
        if source == "photo_now":
            mid = str((await ext.snapshot(cid))["id"])
        elif source == "last_media":
            items = await ext.call("media.list", {"camera": cid, "limit": 1})
            mid = str(items[0]["id"]) if items else None
        elif source == "record_clip":
            job = await ext.clip(cid, seconds)
            found = await wait_clip(cid, job if isinstance(job, dict) else {}, seconds)
            mid = str(found["id"]) if found else None
        if not mid:
            ext.log.warning("no %s media for camera %s, sending text only", source, cid or "-")
            reason = tr(state["lang"], "no_clip" if source == "record_clip" else "no_media")
            await send("\n\n".join(x for x in (text.strip(), reason) if x), ",".join(chats), once=False)
            return
        res = await deliver(chats, text, mid, silent)
        ext.log.info("media %s sent to %d chats, fallback %s", mid, res["sent"], res["fallback"])
    except Exception as e:
        ext.log.exception("media for camera %s not sent", cid or "-")
        await report_failure(f"{source}: {e}"[:300])


@ext.block("media")
async def media_block(params: dict, tok: dict, dry: bool) -> dict:
    text, to = str(params.get("text") or ""), str(params.get("to") or "")
    source = str(params.get("media") or "photo_now")
    if source not in SOURCES:
        source = "photo_now"
    seconds = max(3, min(int(params.get("seconds") or 15), 120))
    chats, unknown = pick(recipients(), to)
    if unknown:
        ext.log.warning("unknown recipients: %s", ", ".join(unknown))
    trace: dict[str, Any] = {"text": text, "count": len(chats)}
    if not token() or not chats:
        ext.log.info("not configured, media not sent")
        return {"outs": [[0]], "trace": {"s": "skip", "m": "ext_sent", "p": {**trace, "reason": "not_configured"}}}
    mid = flow_media(tok) if source == "from_flow" else None
    cid, name = await camera_of(params, tok) if source != "from_flow" or not mid else ("", "")
    if source == "from_flow" and not mid:
        return {"outs": [[0]], "trace": {"s": "skip", "m": "ext_sent", "p": {**trace, "reason": "no_media"}}}
    if source != "from_flow" and not cid:
        return {"outs": [[0]], "trace": {"s": "fail", "m": "ext_sent", "p": {**trace, "reason": "no_camera"}}}
    if dry:
        return {"outs": [[0]], "trace": {"s": "skip", "m": "dry_ext", "p": trace}}
    if not dedupe.allow(f"media|{','.join(chats)}|{cid or mid}|{text}", float(ext.settings.get("dedupe") or 0)):
        return {"outs": [[0]], "trace": {"s": "skip", "m": "ext_sent", "p": {**trace, "reason": "duplicate"}}}
    silent = bool(params.get("silent")) or quiet(str(ext.settings.get("quiet") or ""), datetime.now(state["tz"]))
    ext.spawn(send_media(chats, text, source, cid, mid, seconds, silent))
    m = "tg_clip_queued" if source == "record_clip" else "tg_media_queued"
    return {"outs": [[0]], "trace": {"s": "ok", "m": m, "p": {**trace, "name": name, "seconds": seconds}}}


async def reply(chat: Any, text: str) -> None:
    try:
        await call("sendMessage", {"chat_id": chat, "text": text[:4000]})
    except Exception as e:
        ext.log.warning("reply to %s failed: %s", chat, e)


async def on_message(msg: dict[str, Any]) -> None:
    chat, user = msg.get("chat") or {}, msg.get("from") or {}
    remember_chat(chat, user)
    text = str(msg.get("text") or "").strip()
    if not text.startswith("/"):
        return
    cmd = text.split()[0].split("@")[0].lower()
    lang = state["lang"]
    if cmd == "/start":
        await reply(chat["id"], tr(lang, "start", chat=chat["id"]))
        return
    if str(ext.settings.get("commands") or "on") != "on":
        return
    if not allowed(chat.get("id"), user.get("id"), recipients(), admins()):
        ext.log.warning("command %s from unauthorized chat %s user %s", cmd, chat.get("id"), user.get("id"))
        await reply(chat["id"], tr(lang, "denied", chat=chat.get("id"), user=user.get("id")))
        return
    if cmd == "/status":
        devs = await ext.call("devices.list")
        notes = await ext.call("notifications")
        await reply(chat["id"], status_text(state["home"], devs, notes, lang))
    elif cmd == "/devices":
        devs, rooms = await ext.call("devices.list"), await ext.call("rooms")
        await reply(chat["id"], devices_text(devs, rooms, lang))
    else:
        await reply(chat["id"], tr(lang, "help"))


async def on_callback(q: dict[str, Any]) -> None:
    user, msg = q.get("from") or {}, q.get("message") or {}
    chat = (msg.get("chat") or {}).get("id")
    lang = state["lang"]
    data = str(q.get("data") or "")
    if not allowed(chat, user.get("id"), recipients(), admins()):
        ext.log.warning("button from unauthorized chat %s user %s", chat, user.get("id"))
        await call(
            "answerCallbackQuery",
            {"callback_query_id": q["id"], "text": tr(lang, "denied", chat=chat, user=user.get("id"))},
        )
        return
    item = actions.take(data[2:]) if data.startswith("a:") else None
    if item is None:
        await call("answerCallbackQuery", {"callback_query_id": q["id"], "text": tr(lang, "expired")})
        return
    who = user.get("username") or user.get("first_name") or str(user.get("id"))
    try:
        await ext.call("devices.command", {"id": item["device"], "values": item["values"]})
        note = tr(lang, "done", label=item["label"], user=who)
        await ext.call("event", {"text": f"Telegram, {who}: {item['label']}"})
    except Exception as e:
        note = tr(lang, "failed", label=item["label"], error=str(e)[:120])
        ext.log.error("button action failed: %s", e)
    await call("answerCallbackQuery", {"callback_query_id": q["id"], "text": note[:190]})
    try:
        await call(
            "editMessageReplyMarkup",
            {"chat_id": chat, "message_id": msg.get("message_id"), "reply_markup": {"inline_keyboard": []}},
        )
    except Exception as e:
        ext.log.info("keyboard not removed: %s", e)
    await reply(chat, note)


@ext.loop
async def poll() -> None:
    while True:
        if not token():
            await asyncio.sleep(60)
            continue
        try:
            updates = await call(
                "getUpdates",
                {"offset": state["offset"], "timeout": 25, "allowed_updates": ["message", "callback_query"]},
                timeout=40,
            )
        except Exception as e:
            ext.log.warning("getUpdates failed: %s", e)
            await asyncio.sleep(30)
            continue
        for u in updates or []:
            state["offset"] = max(state["offset"], int(u["update_id"]) + 1)
            try:
                if "message" in u:
                    await on_message(u["message"])
                elif "callback_query" in u:
                    await on_callback(u["callback_query"])
            except Exception:
                ext.log.exception("update %s failed", u.get("update_id"))


def page_blocks(note: str | None = None) -> dict[str, Any]:
    rec = recipients()
    found = seen_chats()
    known = {c for _, c in rec}
    blocks: list[dict[str, Any]] = []
    if note:
        blocks.append({"type": "text", "text": note})
    if bad := rejected_recipients(recipients_text()):
        blocks.append({"type": "text", "text": tr(state["lang"], "rejected", list=", ".join(bad))})
    blocks.append(
        {
            "type": "stats",
            "items": [
                {"label": {"uk": "Отримувачі", "ru": "Получатели", "en": "Recipients"}, "value": len(rec), "digits": 0},
                {
                    "label": {"uk": "Знайдено чатів", "ru": "Найдено чатов", "en": "Chats found"},
                    "value": len(found),
                    "digits": 0,
                },
                {"label": {"uk": "Токен", "ru": "Токен", "en": "Token"}, "value": "OK" if token() else "-"},
            ],
        }
    )
    blocks.append(
        {
            "type": "list",
            "label": {"uk": "Отримувачі", "ru": "Получатели", "en": "Recipients"},
            "items": [{"text": n, "value": c} for n, c in rec],
        }
    )
    blocks.append(
        {
            "type": "list",
            "label": {
                "uk": "Чати, що писали боту. Скопіюйте рядок у поле Отримувачі",
                "ru": "Чаты, писавшие боту. Скопируйте строку в поле Получатели",
                "en": "Chats that messaged the bot. Copy a line into the Recipients field",
            },
            "items": [
                {"text": f"{v['title']}={cid}", "value": "OK" if cid in known else v.get("type") or ""}
                for cid, v in sorted(found.items(), key=lambda x: -x[1].get("last", 0))
            ],
        }
    )
    blocks.append(
        {
            "type": "actions",
            "items": [
                {"key": "refresh", "label": {"uk": "Оновити", "ru": "Обновить", "en": "Refresh"}},
                {
                    "key": "test",
                    "label": {"uk": "Надіслати тест", "ru": "Отправить тест", "en": "Send test"},
                    "primary": True,
                },
            ],
        }
    )
    return {"blocks": blocks, "updated": time.time()}


@ext.page("telegram")
async def page(params: dict) -> dict:
    if params.get("action") == "test":
        res = await send(tr(state["lang"], "test"), level="crit", once=False)
        lang = state["lang"]
        if res.get("failed"):
            note = tr(lang, "test_failed", n=res["failed"])
        elif res.get("sent"):
            note = tr(lang, "test_sent", n=res["sent"])
        else:
            note = tr(lang, "test_none")
        return page_blocks(note)
    return page_blocks()


if __name__ == "__main__":
    ext.run()
