"""Demo language model for the demo environment, OpenAI compatible chat completions with streaming.

Answers by simple rules and calls Valo assistant tools, so the assistant works in the demo without an
OpenRouter key. Scenarios: home overview, batteries, dashboard with a plug voltage chart, turning a plug on.
"""

import asyncio
import json
import logging
import re
import time
from typing import Any

log = logging.getLogger("mocks.llm")
MODEL = "valo/demo"


def lang_of(text: str) -> str:
    if re.search(r"[іїєґ]", text, re.I):
        return "uk"
    return "ru" if re.search(r"[а-яё]", text, re.I) else "en"


TEXT = {
    "overview": {
        "ru": "В доме **{home}** устройств {devices}, помещений {rooms}. Не на связи: {offline}. Тревог: {alarms}.",
        "uk": "У будинку **{home}** пристроїв {devices}, приміщень {rooms}. Без зв'язку: {offline}. Тривог: {alarms}.",
        "en": "Home **{home}** has {devices} devices in {rooms} rooms. Offline: {offline}. Alarms: {alarms}.",
    },
    "battery": {
        "ru": "Низкий заряд: {list}.",
        "uk": "Низький заряд: {list}.",
        "en": "Low battery: {list}.",
    },
    "board": {
        "ru": "Создал панель **{name}** с графиком напряжения **{device}**. Откройте ее из карточки или отмените.",
        "uk": "Створив панель **{name}** з графіком напруги розетки **{device}**. Відкрийте її з картки або скасуйте.",
        "en": "Created dashboard **{name}** with a voltage chart of **{device}**. Open it from the card or undo.",
    },
    "command": {
        "ru": "Подготовил включение **{device}**. Нажмите **Выполнить** в карточке.",
        "uk": "Підготував увімкнення **{device}**. Натисніть **Виконати** у картці.",
        "en": "Prepared turning on **{device}**. Press **Execute** on the card.",
    },
    "none": {"ru": "нет", "uk": "немає", "en": "none"},
    "missing": {
        "ru": "Подходящую розетку не нашел.",
        "uk": "Відповідної розетки не знайшов.",
        "en": "No suitable plug found.",
    },
}


def say(key: str, lang: str, **kw: Any) -> str:
    return TEXT[key][lang].format(**kw)


def intent(text: str) -> str:
    t = text.lower()
    if re.search(r"панел|dashboard", t) and re.search(r"напряж|напруг|voltage", t):
        return "board"
    if re.search(r"включи|увімкни|turn on|switch on", t):
        return "command"
    if re.search(r"заряд|батар|batter", t):
        return "battery"
    return "overview"


def plan(messages: list[dict[str, Any]]) -> tuple[str, Any]:
    """Следующий шаг: ("tool", (имя, аргументы)) или ("text", строка)."""
    last = max(
        (
            i
            for i, m in enumerate(messages)
            if m.get("role") == "user" and not str(m.get("content", "")).startswith("[Valo]")
        ),
        default=0,
    )
    question = str(messages[last].get("content") or "")
    lang, want = lang_of(question), intent(question)
    tail = messages[last + 1 :]
    results = [
        json.loads(m["content"])
        for m in tail
        if m.get("role") == "tool" and m.get("content", "").startswith(("{", "["))
    ]
    step = len([m for m in tail if m.get("role") == "assistant"])
    if want in ("overview", "battery"):
        if step == 0:
            return "tool", ("home_overview", {})
        o = results[-1] if results else {}
        if want == "battery":
            return "text", say("battery", lang, list=", ".join(o.get("lowBattery") or []) or say("none", lang))
        return "text", say(
            "overview",
            lang,
            home=o.get("home", "-"),
            devices=o.get("devices", 0),
            rooms=len(o.get("rooms") or []),
            offline=", ".join(o.get("offline") or []) or say("none", lang),
            alarms=", ".join(o.get("alarms") or []) or say("none", lang),
        )
    if step == 0:
        return "tool", ("list_devices", {"kind": "plug"})
    plugs = (results[0].get("devices") if results and isinstance(results[0], dict) else None) or []
    fit = [d for d in plugs if want != "board" or "v" in (d.get("state") or {})]
    named = [d for d in fit if str(d.get("name") or "").lower() in question.lower()]
    plug = next(iter(named or fit), None)
    if plug is None:
        return "text", say("missing", lang)
    if step == 1 and want == "board":
        name = {"ru": "Напряжение", "uk": "Напруга", "en": "Voltage"}[lang]
        widgets = [
            {"type": "chart", "device": plug["id"], "cap": "v", "hours": 24, "size": "wide"},
            {"type": "plug", "device": plug["id"]},
        ]
        return "tool", ("create_dashboard", {"name": name, "widgets": widgets})
    if step == 1:
        return "tool", ("device_command", {"device_id": plug["id"], "values": {"on": True}})
    if want == "board":
        made = results[-1].get("result", {}) if isinstance(results[-1], dict) else {}
        return "text", say("board", lang, name=made.get("name", "-"), device=plug["name"])
    return "text", say("command", lang, device=plug["name"])


def chunk(delta: dict[str, Any], finish: str | None = None) -> bytes:
    body = {
        "id": "chatcmpl-demo",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": MODEL,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }
    return f"data: {json.dumps(body, ensure_ascii=False)}\n\n".encode()


async def answer(w: asyncio.StreamWriter, req: dict[str, Any]) -> None:
    kind, value = plan(req.get("messages") or []) if req.get("tools") else ("text", "OK")
    w.write(
        b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nCache-Control: no-cache\r\nConnection: close\r\n\r\n"
    )
    w.write(chunk({"role": "assistant"}))
    if kind == "tool":
        name, args = value
        call = {
            "index": 0,
            "id": f"call_{int(time.time() * 1000)}",
            "type": "function",
            "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)},
        }
        w.write(chunk({"tool_calls": [call]}, "tool_calls"))
    else:
        for word in re.findall(r"\S+\s*", value):
            w.write(chunk({"content": word}))
            await w.drain()
            await asyncio.sleep(0.03)
        w.write(chunk({}, "stop"))
    usage = {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}
    w.write(
        b"data: "
        + json.dumps(
            {"id": "chatcmpl-demo", "object": "chat.completion.chunk", "created": int(time.time()), "model": MODEL}
            | {"choices": [], "usage": usage}
        ).encode()
        + b"\n\n"
    )
    w.write(b"data: [DONE]\n\n")


def reply(w: asyncio.StreamWriter, status: str, body: Any) -> None:
    raw = json.dumps(body).encode()
    w.write(
        f"HTTP/1.1 {status}\r\nContent-Type: application/json\r\n".encode()
        + f"Content-Length: {len(raw)}\r\nConnection: close\r\n\r\n".encode()
        + raw
    )


async def handle(r: asyncio.StreamReader, w: asyncio.StreamWriter) -> None:
    try:
        head = await r.readuntil(b"\r\n\r\n")
        lines = head.decode("latin-1").split("\r\n")
        method, path, _ = lines[0].split(" ", 2)
        headers = {k.lower(): v.strip() for k, _, v in (ln.partition(":") for ln in lines[1:] if ln)}
        body = await r.readexactly(int(headers.get("content-length") or 0))
        if method == "GET" and path.rstrip("/").endswith("/models"):
            reply(
                w,
                "200 OK",
                {
                    "object": "list",
                    "data": [{"id": MODEL, "object": "model", "name": "Valo demo", "context_length": 8000}],
                },
            )
        elif method == "POST" and path.rstrip("/").endswith("/chat/completions"):
            req = json.loads(body or b"{}")
            if req.get("stream"):
                await answer(w, req)
            else:
                kind, value = plan(req.get("messages") or [])
                text = value if kind == "text" else ""
                reply(
                    w,
                    "200 OK",
                    {
                        "id": "chatcmpl-demo",
                        "object": "chat.completion",
                        "created": int(time.time()),
                        "model": MODEL,
                        "choices": [
                            {"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}
                        ],
                    },
                )
        else:
            reply(w, "404 Not Found", {"error": {"message": "not found"}})
        await w.drain()
    except (asyncio.IncompleteReadError, ValueError, ConnectionError) as e:
        log.warning("demo llm request failed: %s", e)
    finally:
        w.close()


async def serve(port: int = 8090) -> None:
    server = await asyncio.start_server(handle, "0.0.0.0", port)
    log.info("demo llm on :%s", port)
    async with server:
        await server.serve_forever()
