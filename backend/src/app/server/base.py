import ipaddress
import time
from functools import cache
from typing import Any

from litestar import Request, Response
from litestar.connection import ASGIConnection
from litestar.exceptions import HTTPException, NotFoundException, ValidationException
from litestar.handlers import BaseRouteHandler
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import commit, session
from app.domain import auth
from app.domain.common import Principal
from app.lib import log
from app.lib.errors import ApplicationError, message, pick_lang
from app.lib.settings import settings

_log = log.get("http")
_CODES = {401: "unauthorized", 403: "forbidden", 404: "not_found", 405: "not_found", 429: "rate_limited"}


def token_of(conn: ASGIConnection) -> str:
    h = conn.headers.get("authorization", "")
    if h.lower().startswith("bearer "):
        return h[7:].strip()
    return conn.cookies.get("valo_token", "")


@cache
def _trusted() -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    nets = []
    for item in settings.trusted_proxies.split(","):
        try:
            nets.append(ipaddress.ip_network(item.strip(), strict=False))
        except ValueError:
            if item.strip():
                _log.warning("trusted_proxy_invalid", value=item.strip())
    return tuple(nets)


def trusted(addr: str) -> bool:
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    return any(ip in n for n in _trusted())


def client_ip(conn: ASGIConnection) -> str:
    peer = conn.client.host if conn.client else ""
    if not trusted(peer):
        return peer
    hops = [h.strip() for h in conn.headers.get("x-forwarded-for", "").split(",") if h.strip()]
    for hop in reversed(hops):
        if not trusted(hop):
            return hop
    return hops[0] if hops else peer


async def authed(conn: ASGIConnection, _: BaseRouteHandler) -> None:
    tok, p = token_of(conn), None
    if tok:
        async with session() as s:
            p = await auth.resolve(s, tok)
    if p is None:
        raise ApplicationError("unauthorized", 401)
    conn.state.principal = p


async def principal(request: Request) -> Principal:
    return request.state.principal


async def done(s: AsyncSession, result: Any = None) -> Any:
    await commit(s)
    return result


def problem(request: Request, exc: Exception) -> Response:
    if isinstance(exc, ApplicationError):
        status, code, params = exc.status, exc.code, exc.params
    elif isinstance(exc, ValidationException):
        status, code = 422, "validation"
        params = {
            "detail": "; ".join(
                f"{e.get('key', '')} {e.get('message', '')}".strip() for e in (exc.extra or []) if isinstance(e, dict)
            )[:300]
            or str(exc.detail)
        }
    elif isinstance(exc, NotFoundException):
        status, code, params = 404, "not_found", {}
    elif isinstance(exc, HTTPException):
        status, code, params = exc.status_code, _CODES.get(exc.status_code, "internal"), {}
    else:
        status, code, params = 500, "internal", {}
        _log.error("unhandled", path=request.url.path, method=request.method, error=repr(exc), exc_info=exc)
    title = message(code, pick_lang(request.headers.get("accept-language")), **params)
    if status >= 500 and code != "internal":
        _log.warning("request_failed", path=request.url.path, code=code, status=status)
    body = {
        "type": f"urn:valo:error:{code}",
        "title": title,
        "status": status,
        "code": code,
        "detail": title,
        "instance": request.url.path,
        "params": params,
    }
    return Response(body, status_code=status, media_type="application/problem+json")


def access_log(app: Any) -> Any:
    async def mw(scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await app(scope, receive, send)
            return
        t0, st = time.perf_counter(), {}

        async def _send(msg: dict) -> None:
            if msg["type"] == "http.response.start":
                st["s"] = msg["status"]
            await send(msg)

        try:
            await app(scope, receive, _send)
        finally:
            _log.info(
                "request",
                method=scope.get("method"),
                path=scope.get("path"),
                status=st.get("s"),
                ms=round((time.perf_counter() - t0) * 1000, 1),
            )

    return mw
