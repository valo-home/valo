"""Помощники для драйверов камер: адреса с учетными данными и проверка RTSP без чтения видео."""

import asyncio
import base64
import hashlib
import re
from urllib.parse import quote, urlsplit, urlunsplit
from xml.sax.saxutils import escape

TIMEOUT = 8


class CameraError(Exception):
    """Понятная пользователю причина, по которой камеру нельзя добавить."""


class AuthError(CameraError):
    """Камера отвечает, но не принимает логин, пароль или ключ."""


async def tcp_open(host: str, port: int, timeout: float = 1.0) -> bool:
    """Открыт ли порт на узле. Без чтения данных."""
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout)
    except OSError, TimeoutError:
        return False
    writer.close()
    return True


async def sweep(hosts: list[str], port: int, limit: int = 64, timeout: float = 1.0) -> list[str]:
    """Узлы из списка, на которых открыт порт. Одновременно не больше limit попыток."""
    gate = asyncio.Semaphore(limit)

    async def one(h: str) -> str | None:
        async with gate:
            return h if await tcp_open(h, port, timeout) else None

    return [h for h in await asyncio.gather(*(one(h) for h in hosts)) if h]


def with_auth(url: str, user: str, password: str) -> str:
    """Вставить логин и пароль в адрес потока. Если в адресе уже есть учетные данные, они заменяются."""
    u = urlsplit(url.strip())
    if not u.scheme or not u.hostname:
        raise CameraError("stream address is invalid")
    host = u.netloc.rpartition("@")[2]
    if user:
        host = f"{quote(user, safe='')}:{quote(password, safe='')}@{host}"
    return urlunsplit((u.scheme, host, u.path, u.query, u.fragment))


def _digest(www: str, method: str, uri: str, user: str, pw: str) -> str:
    f = dict(re.findall(r'(\w+)="?([^",]*)"?', www))
    realm, nonce = f.get("realm", ""), f.get("nonce", "")
    ha1 = hashlib.md5(f"{user}:{realm}:{pw}".encode()).hexdigest()
    ha2 = hashlib.md5(f"{method}:{uri}".encode()).hexdigest()
    resp = hashlib.md5(f"{ha1}:{nonce}:{ha2}".encode()).hexdigest()
    return f'Digest username="{user}", realm="{realm}", nonce="{nonce}", uri="{uri}", response="{resp}"'


async def _ask(host: str, port: int, req: str) -> tuple[int, dict[str, str]]:
    reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), TIMEOUT)
    try:
        writer.write(req.encode())
        await writer.drain()
        head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), TIMEOUT)
    finally:
        writer.close()
    lines = head.decode(errors="replace").split("\r\n")
    m = re.match(r"RTSP/1\.\d (\d{3})", lines[0])
    if not m:
        raise CameraError("not an RTSP server")
    hdr: dict[str, str] = {}
    for ln in lines[1:]:
        k, _, v = ln.partition(":")
        if k:
            hdr.setdefault(k.strip().lower(), v.strip())
    return int(m[1]), hdr


async def rtsp_check(url: str, user: str = "", password: str = "") -> None:
    """Проверить адрес, логин и пароль потока запросом DESCRIBE. Ошибка CameraError с понятной причиной."""
    u = urlsplit(url)
    if u.scheme not in ("rtsp", "rtsps") or not u.hostname:
        raise CameraError("stream address must start with rtsp://")
    try:
        explicit = u.port
    except ValueError as e:
        raise CameraError("stream port is invalid") from e
    user = user or (u.username or "")
    password = password or (u.password or "")
    netloc = u.netloc.rpartition("@")[2]
    uri = urlunsplit((u.scheme, netloc, u.path or "/", u.query, ""))
    base = f"DESCRIBE {uri} RTSP/1.0\r\nCSeq: 1\r\nAccept: application/sdp\r\nUser-Agent: valo\r\n"
    port = explicit or (322 if u.scheme == "rtsps" else 554)
    try:
        code, hdr = await _ask(u.hostname, port, base + "\r\n")
        if code == 401 and user:
            www = hdr.get("www-authenticate", "")
            if www.lower().startswith("digest"):
                auth = _digest(www, "DESCRIBE", uri, user, password)
            else:
                auth = "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()
            code, _ = await _ask(
                u.hostname, port, base.replace("CSeq: 1", "CSeq: 2") + f"Authorization: {auth}\r\n\r\n"
            )
    except (OSError, TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError, ValueError) as e:
        raise CameraError(f"RTSP port of {u.hostname} does not answer") from e
    if code == 401:
        raise AuthError("stream login or password is wrong")
    if code == 404:
        raise CameraError(f"stream {u.path or '/'} not found")
    if code >= 400:
        raise CameraError(f"RTSP error {code}")


WSSE = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd"
WSU = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd"
DIGEST = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0#PasswordDigest"
B64 = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-soap-message-security-1.0#Base64Binary"
EV = "http://www.onvif.org/ver10/events/wsdl"
MOTION_TOPICS = ("MotionAlarm", "CellMotionDetector/Motion", "MotionDetector/Motion")
MOTION_ITEMS = ("State", "IsMotion", "Motion")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def onvif_messages(xml: str) -> list[tuple[str, dict[str, str]]]:
    """Темы и значения из ответа PullMessages."""
    import xml.etree.ElementTree as ET

    try:
        root = ET.fromstring(xml)
    except ET.ParseError as e:
        raise CameraError(f"ONVIF answer is not XML: {e}") from e
    out = []
    for n in root.iter():
        if _local(n.tag) != "NotificationMessage":
            continue
        topic = next((x.text or "" for x in n.iter() if _local(x.tag) == "Topic"), "").strip()
        data: dict[str, str] = {}
        for x in n.iter():
            if _local(x.tag) == "Data":
                for it in x.iter():
                    if _local(it.tag) == "SimpleItem" and it.get("Name"):
                        data[it.get("Name", "")] = it.get("Value", "")
        out.append((topic, data))
    return out


def onvif_motion(messages: list[tuple[str, dict[str, str]]]) -> bool | None:
    """Последнее состояние движения из сообщений ONVIF или None, если о движении ничего нет."""
    state = None
    for topic, data in messages:
        if not any(t in topic for t in MOTION_TOPICS):
            continue
        for k in MOTION_ITEMS:
            if k in data:
                state = data[k].strip().lower() in ("true", "1", "active")
                break
    return state


class Onvif:
    """Минимальный клиент событий ONVIF (PullPoint) с паролем WS-Security."""

    def __init__(self, host: str, user: str, password: str, port: int = 80) -> None:
        self.host, self.port, self.user, self.password = host, port, user, password

    def _security(self) -> str:
        import datetime
        import os

        nonce = os.urandom(16)
        created = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        dig = base64.b64encode(hashlib.sha1(nonce + created.encode() + self.password.encode()).digest()).decode()
        return (
            f'<Security s:mustUnderstand="1" xmlns="{WSSE}"><UsernameToken><Username>{escape(self.user)}</Username>'
            f'<Password Type="{DIGEST}">{dig}</Password><Nonce EncodingType="{B64}">'
            f"{base64.b64encode(nonce).decode()}</Nonce>"
            f'<Created xmlns="{WSU}">{created}</Created></UsernameToken></Security>'
        )

    async def call(self, url: str, body: str, timeout: float = TIMEOUT) -> str:
        u = urlsplit(url if "://" in url else f"http://{self.host}{url}")
        to = f'<a:To xmlns:a="http://www.w3.org/2005/08/addressing">{url}</a:To>' if "?" in url else ""
        env = (
            '<?xml version="1.0" encoding="UTF-8"?><s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope">'
            f"<s:Header>{self._security()}{to}</s:Header><s:Body>{body}</s:Body></s:Envelope>"
        ).encode()
        path = u.path + (f"?{u.query}" if u.query else "")
        req = (
            f"POST {path} HTTP/1.0\r\nHost: {u.netloc}\r\nContent-Type: application/soap+xml; charset=utf-8\r\n"
            f"Content-Length: {len(env)}\r\nUser-Agent: valo\r\n\r\n"
        ).encode() + env
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(u.hostname or self.host, u.port or self.port), TIMEOUT
            )
            try:
                writer.write(req)
                await writer.drain()
                raw = await asyncio.wait_for(reader.read(), timeout)
            finally:
                writer.close()
        except (OSError, TimeoutError) as e:
            raise CameraError(f"ONVIF of {self.host} does not answer") from e
        head, _, body_ = raw.partition(b"\r\n\r\n")
        status = head.split(b"\r\n", 1)[0].decode(errors="replace")
        text = body_.decode(errors="replace")
        if " 200" not in status:
            reason = re.search(r"<(?:\w+:)?Text[^>]*>([^<]+)<", text)
            raise CameraError(
                f"ONVIF {status.partition(' ')[2] or status}: {reason.group(1) if reason else ''}".strip()
            )
        return text

    async def subscribe(self, seconds: int = 300) -> str:
        xml = await self.call(
            "/onvif/events_service",
            f'<CreatePullPointSubscription xmlns="{EV}"><InitialTerminationTime>PT{seconds}S</InitialTerminationTime>'
            "</CreatePullPointSubscription>",
        )
        m = re.search(r"<(?:\w+:)?Address>([^<]+)</", xml)
        if not m:
            raise CameraError("ONVIF did not return a pull point")
        return m.group(1).strip()

    async def pull(self, addr: str, wait: int = 20) -> list[tuple[str, dict[str, str]]]:
        xml = await self.call(
            addr,
            f'<PullMessages xmlns="{EV}"><Timeout>PT{wait}S</Timeout><MessageLimit>20</MessageLimit></PullMessages>',
            timeout=wait + TIMEOUT,
        )
        return onvif_messages(xml)

    async def renew(self, addr: str, seconds: int = 300) -> None:
        await self.call(
            addr,
            '<Renew xmlns="http://docs.oasis-open.org/wsn/b-2">'
            f"<TerminationTime>PT{seconds}S</TerminationTime></Renew>",
        )

    async def unsubscribe(self, addr: str) -> None:
        await self.call(addr, '<Unsubscribe xmlns="http://docs.oasis-open.org/wsn/b-2"/>')
