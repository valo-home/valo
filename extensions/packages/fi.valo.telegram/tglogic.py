"""Логика расширения Telegram без сети и MQTT: получатели, права, повторы, кнопки, тексты бота."""

import json
import pathlib
import re
import secrets
import time
from datetime import datetime
from typing import Any

TEXTS = {
    "uk": {
        "test_sent": "Тест надіслано, чатів: {n}",
        "test_none": "Не надіслано: немає токена або отримувачів",
        "rejected": (
            "Не прийнято в полі Отримувачі: {list}. "
            "Потрібен числовий chat id, бот повідомить його у відповідь на /start"
        ),
        "not_found": (
            "Бота немає в цьому чаті або номер чату змінився. "
            "Напишіть боту /start у потрібному чаті та вкажіть номер з відповіді"
        ),
        "test_failed": "Помилок доставки: {n}, деталі в Система, Помилки",
        "start": "Chat id цього чату: {chat}. Додайте його в налаштування розширення Telegram у Valo, поле Отримувачі",
        "denied": "Немає доступу. Chat id {chat}, user id {user}",
        "help": "/status стан будинку\n/devices пристрої\n/help ця довідка",
        "status": "{home}: пристроїв {n}, не на зв'язку {off}, тривог {alarms}",
        "alarms": "Тривоги: {list}",
        "offline": "Не на зв'язку: {list}",
        "low": "Низький заряд: {list}",
        "notes": "Сповіщення:",
        "no_notes": "Активних сповіщень немає",
        "done": "{label}: виконано ({user})",
        "failed": "{label}: помилка {error}",
        "expired": "Кнопка застаріла",
        "test": "Тестове повідомлення Valo. Доставка працює",
        "none": "немає",
        "no_room": "Без приміщення",
        "on": "увімкнено",
        "off": "вимкнено",
        "offline_mark": "не на зв'язку",
        "too_big": "Файл завеликий для Telegram ({size} МБ)",
        "not_sent_media": "Файл не надіслано: {error}",
        "open": "Відкрити у Valo: {link}",
        "in_valo": "Запис є у Valo, розділ Камери",
        "no_clip": "Кліп не записано: камера недоступна або мало місця",
        "no_media": "Записів камери ще немає",
    },
    "ru": {
        "test_sent": "Тест отправлен, чатов: {n}",
        "test_none": "Не отправлено: нет токена или получателей",
        "rejected": "Не принято в поле Получатели: {list}. Нужен числовой chat id, бот сообщит его в ответ на /start",
        "not_found": (
            "Бота нет в этом чате или номер чата сменился. Напишите боту /start в нужном чате и укажите номер из ответа"
        ),
        "test_failed": "Ошибок доставки: {n}, подробности в Система, Ошибки",
        "start": "Chat id этого чата: {chat}. Добавьте его в настройки расширения Telegram в Valo, поле Получатели",
        "denied": "Нет доступа. Chat id {chat}, user id {user}",
        "help": "/status состояние дома\n/devices устройства\n/help эта справка",
        "status": "{home}: устройств {n}, не на связи {off}, тревог {alarms}",
        "alarms": "Тревоги: {list}",
        "offline": "Не на связи: {list}",
        "low": "Низкий заряд: {list}",
        "notes": "Уведомления:",
        "no_notes": "Активных уведомлений нет",
        "done": "{label}: выполнено ({user})",
        "failed": "{label}: ошибка {error}",
        "expired": "Кнопка устарела",
        "test": "Тестовое сообщение Valo. Доставка работает",
        "none": "нет",
        "no_room": "Без помещения",
        "on": "включено",
        "off": "выключено",
        "offline_mark": "не на связи",
        "too_big": "Файл слишком большой для Telegram ({size} МБ)",
        "not_sent_media": "Файл не отправлен: {error}",
        "open": "Открыть в Valo: {link}",
        "in_valo": "Запись есть в Valo, раздел Камеры",
        "no_clip": "Клип не записан: камера недоступна или мало места",
        "no_media": "Записей камеры пока нет",
    },
    "en": {
        "test_sent": "Test sent, chats: {n}",
        "test_none": "Not sent: no token or recipients",
        "rejected": (
            "Not accepted in the Recipients field: {list}. "
            "A numeric chat id is needed, the bot replies with it to /start"
        ),
        "not_found": (
            "The bot is not in this chat or the chat number has changed. "
            "Send /start to the bot in that chat and use the number from the reply"
        ),
        "test_failed": "Delivery errors: {n}, see System, Errors",
        "start": "Chat id of this chat: {chat}. Add it to the Telegram extension settings in Valo, Recipients field",
        "denied": "Access denied. Chat id {chat}, user id {user}",
        "help": "/status home status\n/devices devices\n/help this help",
        "status": "{home}: devices {n}, offline {off}, alarms {alarms}",
        "alarms": "Alarms: {list}",
        "offline": "Offline: {list}",
        "low": "Low battery: {list}",
        "notes": "Notifications:",
        "no_notes": "No active notifications",
        "done": "{label}: done ({user})",
        "failed": "{label}: failed {error}",
        "expired": "This button has expired",
        "test": "Valo test message. Delivery works",
        "none": "none",
        "no_room": "No room",
        "on": "on",
        "off": "off",
        "offline_mark": "offline",
        "too_big": "The file is too large for Telegram ({size} MB)",
        "not_sent_media": "The file was not sent: {error}",
        "open": "Open in Valo: {link}",
        "in_valo": "The recording is in Valo, Cameras section",
        "no_clip": "The clip was not recorded: the camera is unavailable or space is low",
        "no_media": "The camera has no recordings yet",
    },
}
ALARM_CAPS = ("leak", "smoke", "co", "gas")
_SPLIT = re.compile(r"[;\n,]+")
_MEDIA = re.compile(r"(?:/api/v1/media/)?([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})")
PHOTO_MAX = 10 * 1024 * 1024
VIDEO_MAX = 50 * 1024 * 1024
CAPTION_MAX = 1024
SOURCES = ("photo_now", "from_flow", "last_media", "record_clip")


def tr(lang: str, key: str, **params: Any) -> str:
    return (TEXTS.get(lang) or TEXTS["en"])[key].format(**params)


def _recipient_lines(text: str) -> list[tuple[str, str, str]]:
    out: list[tuple[str, str, str]] = []
    for part in _SPLIT.split(text or ""):
        part = part.strip()
        if not part:
            continue
        name, sep, chat = part.partition("=")
        name, chat = (name.strip(), chat.strip()) if sep else (part, part)
        out.append((part, name, chat))
    return out


def parse_recipients(text: str) -> list[tuple[str, str]]:
    return [(name, chat) for _, name, chat in _recipient_lines(text) if re.fullmatch(r"-?\d+", chat)]


def rejected_recipients(text: str) -> list[str]:
    """Строки поля Получатели без числового chat id, например @имя. Telegram не дает боту писать по имени."""
    return [part for part, _, chat in _recipient_lines(text) if not re.fullmatch(r"-?\d+", chat)]


def delivery_hint(lang: str, error: str) -> str:
    """Пояснение к ошибке доставки, если ее причина обычно в настройках получателей."""
    return tr(lang, "not_found") if "chat not found" in error.lower() else ""


def parse_ids(text: str) -> set[str]:
    return {x.strip() for x in _SPLIT.split(text or "") if re.fullmatch(r"\s*-?\d+\s*", x)}


def pick(recipients: list[tuple[str, str]], to: str) -> tuple[list[str], list[str]]:
    if not (to or "").strip():
        return sorted({c for _, c in recipients}), []
    chats, unknown = [], []
    for want in _SPLIT.split(to):
        want = want.strip()
        if not want:
            continue
        found = [c for n, c in recipients if n.lower() == want.lower() or c == want]
        if found:
            chats += found
        else:
            unknown.append(want)
    return sorted(set(chats)), unknown


def allowed(chat: Any, user: Any, recipients: list[tuple[str, str]], admins: set[str]) -> bool:
    if str(chat) not in {c for _, c in recipients}:
        return False
    return not admins or str(user) in admins


def quiet(spec: str, now: datetime) -> bool:
    if "-" not in (spec or ""):
        return False
    try:
        a, b = (datetime.strptime(x.strip(), "%H:%M").time() for x in spec.split("-", 1))
    except ValueError:
        return False
    t = now.time()
    return a <= t < b if a <= b else t >= a or t < b


class Dedupe:
    def __init__(self) -> None:
        self.seen: dict[str, float] = {}

    def allow(self, key: str, minutes: float, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        if minutes <= 0:
            return True
        self.seen = {k: v for k, v in self.seen.items() if now - v < minutes * 60}
        if key in self.seen:
            return False
        self.seen[key] = now
        return True


class Actions:
    """Действия кнопок. callback_data у Telegram не длиннее 64 байт, поэтому в кнопке только ключ."""

    TTL = 86400

    def __init__(self, path: pathlib.Path) -> None:
        self.path = path
        try:
            self.items: dict[str, dict[str, Any]] = json.loads(path.read_text("utf-8"))
        except OSError, ValueError:
            self.items = {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.items), "utf-8")

    def add(self, device: str, values: dict[str, Any], label: str, now: float | None = None) -> str:
        now = time.time() if now is None else now
        self.items = {k: v for k, v in self.items.items() if v["exp"] > now}
        key = secrets.token_urlsafe(9)
        self.items[key] = {"device": device, "values": values, "label": label, "exp": now + self.TTL}
        self._save()
        return key

    def take(self, key: str, now: float | None = None) -> dict[str, Any] | None:
        now = time.time() if now is None else now
        item = self.items.pop(key, None)
        self._save()
        return item if item and item["exp"] > now else None


def buttons(params: dict[str, Any], token: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    device = str(params.get("device") or token.get("d") or "")
    out = []
    for i in (1, 2):
        label = str(params.get(f"b{i}_label") or "").strip()
        values = params.get(f"b{i}_values")
        if label and device and isinstance(values, dict) and values:
            out.append((label, device, values))
    return out


def device_line(d: dict[str, Any], lang: str) -> str:
    st = d.get("state") or {}
    if not d.get("available", True):
        return f"{d['name']}: {tr(lang, 'offline_mark')}"
    parts = []
    if isinstance(st.get("on"), bool):
        parts.append(tr(lang, "on") if st["on"] else tr(lang, "off"))
    for k, unit in (("t", "°C"), ("h", "%"), ("w", " W"), ("bat", "% bat")):
        if isinstance(st.get(k), (int, float)):
            parts.append(f"{st[k]:g}{unit}")
    for k in ALARM_CAPS:
        if st.get(k) is True:
            parts.append(k.upper())
    return f"{d['name']}: {', '.join(parts) or '-'}"


def devices_text(devs: list[dict[str, Any]], rooms: list[dict[str, Any]], lang: str, limit: int = 3800) -> str:
    names = {r["id"]: r["name"] for r in rooms}
    groups: dict[str, list[str]] = {}
    for d in sorted(devs, key=lambda x: x.get("name", "")):
        groups.setdefault(names.get(d.get("roomId"), tr(lang, "no_room")), []).append(device_line(d, lang))
    lines = []
    for room in sorted(groups):
        lines.append(room)
        lines += [f"  {x}" for x in groups[room]]
    text = "\n".join(lines) or tr(lang, "none")
    return text if len(text) <= limit else text[:limit] + "\n..."


def status_text(home: str, devs: list[dict[str, Any]], notes: list[dict[str, Any]], lang: str) -> str:
    none = tr(lang, "none")
    off = [d["name"] for d in devs if not d.get("available", True)]
    alarms = [d["name"] for d in devs if any((d.get("state") or {}).get(k) is True for k in ALARM_CAPS)]
    low = [
        f"{d['name']} ({d['state']['bat']}%)"
        for d in devs
        if isinstance((d.get("state") or {}).get("bat"), (int, float)) and d["state"]["bat"] < 15
    ]
    lines = [tr(lang, "status", home=home, n=len(devs), off=len(off), alarms=len(alarms))]
    if alarms:
        lines.append(tr(lang, "alarms", list=", ".join(alarms)))
    if off:
        lines.append(tr(lang, "offline", list=", ".join(off)))
    if low:
        lines.append(tr(lang, "low", list=", ".join(low)))
    lines.append(tr(lang, "notes") if notes else tr(lang, "no_notes"))
    lines += [f"  {n.get('text')}" for n in notes[:15]]
    return "\n".join(lines) or none


def media_id(ref: Any) -> str | None:
    """Идентификатор записи из адреса /api/v1/media/<id>/file или из самого id."""
    m = _MEDIA.search(str(ref or ""))
    return m.group(1).lower() if m else None


def flow_media(token: dict[str, Any]) -> str | None:
    """Запись из переменных сценария: клип важнее снимка."""
    return media_id(token.get("clip")) or media_id(token.get("snapshot")) or media_id(token.get("media"))


def upload_method(kind: str, size: int) -> tuple[str, str] | None:
    """Метод Bot API и поле файла по типу записи, None если Telegram такой файл не примет."""
    if kind == "photo" and 0 < size <= PHOTO_MAX:
        return "sendPhoto", "photo"
    if kind == "video" and 0 < size <= VIDEO_MAX:
        return "sendVideo", "video"
    return None


def caption(text: str) -> str:
    text = (text or "").strip()
    return text if len(text) <= CAPTION_MAX else text[: CAPTION_MAX - 3].rstrip() + "..."


def media_link(base: str, mid: str) -> str:
    base = (base or "").strip().rstrip("/")
    return f"{base}/api/v1/media/{mid}/file" if re.match(r"^https?://[^\s/]+", base) else ""


def fallback_text(lang: str, text: str, reason: str, link: str) -> str:
    tail = tr(lang, "open", link=link) if link else tr(lang, "in_valo")
    return "\n\n".join(x for x in ((text or "").strip(), reason, tail) if x)[:4000]


def multipart(fields: dict[str, str], name: str, filename: str, content: bytes, ctype: str) -> tuple[bytes, str]:
    """Тело multipart/form-data для отправки файла в Bot API."""
    boundary = "valo" + secrets.token_hex(12)
    out = bytearray()
    for k, v in fields.items():
        out += f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
    out += (
        f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
        f"Content-Type: {ctype}\r\n\r\n"
    ).encode()
    out += content
    out += f"\r\n--{boundary}--\r\n".encode()
    return bytes(out), f"multipart/form-data; boundary={boundary}"


def _ts(v: Any) -> float | None:
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def clip_ready(items: list[dict[str, Any]], since: float, origin: str) -> dict[str, Any] | None:
    """Клип, записанный по нашему заданию: видео с нашим origin, созданное не раньше задания."""
    for m in items or []:
        if not isinstance(m, dict) or m.get("kind") != "video" or m.get("origin") != origin:
            continue
        at = _ts(m.get("created_at") or m.get("createdAt"))
        if at is not None and at >= since - 2:
            return m
    return None
