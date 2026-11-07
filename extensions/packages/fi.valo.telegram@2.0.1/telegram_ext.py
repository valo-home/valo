import asyncio
import json
import urllib.parse
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

from valo_sdk import Extension

ext = Extension()
TZ = ZoneInfo("Europe/Helsinki")


def chats() -> list[str]:
    return [c.strip() for c in str(ext.settings.get("chats") or "").split(",") if c.strip()]


def quiet(now: datetime) -> bool:
    spec = str(ext.settings.get("quiet") or "")
    if "-" not in spec or ext.version.startswith("2.0"):
        return False
    a, b = (datetime.strptime(x.strip(), "%H:%M").time() for x in spec.split("-", 1))
    t = now.time()
    return a <= t < b if a <= b else t >= a or t < b


def post(token: str, chat: str, text: str, silent: bool) -> None:
    body = urllib.parse.urlencode(
        {"chat_id": chat, "text": text, "disable_notification": "true" if silent else "false"}
    ).encode()
    with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", data=body, timeout=10) as r:
        json.loads(r.read())


async def send(text: str, level: str = "info", silent: bool = False) -> dict:
    silent = silent or (quiet(datetime.now(TZ)) and level != "crit")
    token, targets = str(ext.settings.get("token") or ""), chats()
    if not token or not targets:
        ext.log.info("demo delivery, no token or chats: %s", text)
        return {"sent": 0, "demo": True}
    sent = 0
    for chat in targets:
        try:
            await asyncio.to_thread(post, token, chat, text, silent)
            sent += 1
        except Exception as e:
            ext.log.warning("telegram %s failed: %s", chat, e)
    return {"sent": sent, "silent": silent}


@ext.service("notify")
async def notify(params: dict) -> dict:
    return await send(str(params.get("text") or ""), str(params.get("level") or "info"))


@ext.block("message")
async def message(params: dict, token: dict, dry: bool) -> dict:
    text = str(params.get("text") or "")
    if dry:
        return {"outs": [[0]], "trace": {"s": "skip", "m": "dry_ext", "p": {"text": text}}}
    res = await send(text, silent=bool(params.get("silent")))
    return {"outs": [[0]], "trace": {"s": "ok", "m": "ext_sent", "p": {"text": text, "count": res.get("sent")}}}


if __name__ == "__main__":
    ext.run()
