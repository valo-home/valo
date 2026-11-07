import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import now
from app.db.models import ApiToken, User
from app.domain import events
from app.domain.common import ROLES, UNSET, Principal, S, Unset, as_uuid, out, patch
from app.lib import log
from app.lib.errors import ApplicationError
from app.lib.kv import hit
from app.lib.security import digest, hash_password, make_jwt, new_secret, read_jwt, verify_password
from app.lib.settings import env_int

SESSION_TTL = env_int("SESSION_TTL", 30 * 86400)
_log = log.get("auth")


class LoginIn(S):
    username: str
    password: str


class UserOut(S):
    id: uuid.UUID
    username: str
    name: str
    role: str
    rooms: list[str]
    lang: str | None
    active: bool
    last_login_at: datetime | None


class UserIn(S):
    username: str
    name: str
    password: str
    role: str = "member"
    rooms: list[str] = []
    lang: str | None = None


class UserPatch(S):
    name: str | Unset = UNSET
    password: str | Unset = UNSET
    role: str | Unset = UNSET
    rooms: list[str] | Unset = UNSET
    lang: str | Unset | None = UNSET
    active: bool | Unset = UNSET


class TokenOut(S):
    id: uuid.UUID
    name: str
    scope: str
    rooms: list[str]
    expires_at: datetime | None
    last_used_at: datetime | None
    created_at: datetime
    user_id: uuid.UUID


class TokenIn(S):
    name: str
    scope: str = "read"
    rooms: list[str] = []
    days: int | None = 90


class Session(S):
    token: str
    user: UserOut


def principal(u: User, scope: str = "full", rooms: list[str] | None = None) -> Principal:
    return Principal(
        id=str(u.id),
        username=u.username,
        name=u.name,
        role=u.role,
        rooms=rooms if rooms else list(u.rooms or []),
        scope=scope,
    )


async def users_count(s: AsyncSession) -> int:
    return await s.scalar(select(func.count()).select_from(User)) or 0


async def login(s: AsyncSession, data: LoginIn, ip: str) -> Session:
    if not await hit(f"login:{ip}", 10, 60):
        raise ApplicationError("rate_limited", 429)
    u = await s.scalar(select(User).where(User.username == data.username.strip().lower()))
    if u is None or not u.active or not verify_password(data.password, u.password_hash):
        _log.info("login_failed", username=data.username, ip=ip)
        raise ApplicationError("bad_credentials", 401)
    u.last_login_at = now()
    await events.add(s, "user.login", actor=f"user:{u.username}", params={"name": u.name})
    return Session(token=make_jwt(str(u.id), "session", SESSION_TTL), user=out(u, UserOut))


async def resolve(s: AsyncSession, token: str) -> Principal | None:
    if token.startswith("valo_"):
        t = await s.scalar(select(ApiToken).where(ApiToken.token_hash == digest(token)))
        if t is None or (t.expires_at and t.expires_at < now()):
            return None
        u = await s.get(User, t.user_id)
        if u is None or not u.active:
            return None
        if not t.last_used_at or now() - t.last_used_at > timedelta(minutes=5):
            t.last_used_at = now()
            await s.commit()
        return principal(u, t.scope, t.rooms)
    data = read_jwt(token, "session") or read_jwt(token, "ws")
    if not data:
        return None
    u = await s.get(User, as_uuid(data["sub"]))
    return principal(u) if u and u.active else None


def ws_ticket(p: Principal) -> str:
    return make_jwt(p.id, "ws", 120)


async def ws_principal(s: AsyncSession, ticket: str) -> Principal | None:
    data = read_jwt(ticket, "ws")
    if not data:
        return None
    u = await s.get(User, as_uuid(data["sub"]))
    return principal(u) if u and u.active else None


def _check_role(role: str) -> None:
    if role not in ROLES:
        raise ApplicationError("validation", 422, detail="role")


async def users(s: AsyncSession, p: Principal) -> list[UserOut]:
    p.need("admin")
    return [out(u, UserOut) for u in (await s.scalars(select(User).order_by(User.created_at))).all()]


async def create_user(s: AsyncSession, p: Principal, data: UserIn) -> UserOut:
    p.need("admin")
    _check_role(data.role)
    if data.role == "owner":
        p.need("owner")
    name = data.username.strip().lower()
    if not name or len(data.password) < 6:
        raise ApplicationError("validation", 422, detail="username, password")
    if await s.scalar(select(User).where(User.username == name)):
        raise ApplicationError("username_taken", 409)
    u = User(
        username=name,
        name=data.name,
        password_hash=hash_password(data.password),
        role=data.role,
        rooms=data.rooms,
        lang=data.lang,
        active=True,
    )
    s.add(u)
    await s.flush()
    await events.add(s, "user.created", actor=p.actor, params={"name": u.name, "role": u.role})
    return out(u, UserOut)


async def _owners(s: AsyncSession) -> int:
    return (
        await s.scalar(select(func.count()).select_from(User).where(User.role == "owner", User.active.is_(True))) or 0
    )


async def update_user(s: AsyncSession, p: Principal, user_id: str, data: UserPatch) -> UserOut:
    u = await s.get(User, as_uuid(user_id))
    if u is None:
        raise ApplicationError("user_not_found", 404)
    if str(u.id) != p.id:
        p.need("admin")
    elif any(not isinstance(getattr(data, f), Unset) for f in ("role", "rooms", "active")):
        p.need("admin")
    if not isinstance(data.role, Unset):
        _check_role(data.role)
        if "owner" in (data.role, u.role):
            p.need("owner")
    demote = u.role == "owner" and ((not isinstance(data.role, Unset) and data.role != "owner") or data.active is False)
    if demote and await _owners(s) <= 1:
        raise ApplicationError("last_owner", 409)
    pw = data.password
    data.password = UNSET
    patch(u, data)
    if isinstance(pw, str):
        if len(pw) < 6:
            raise ApplicationError("validation", 422, detail="password")
        u.password_hash = hash_password(pw)
    await events.add(s, "user.updated", actor=p.actor, params={"name": u.name})
    return out(u, UserOut)


async def delete_user(s: AsyncSession, p: Principal, user_id: str) -> None:
    p.need("admin")
    u = await s.get(User, as_uuid(user_id))
    if u is None:
        raise ApplicationError("user_not_found", 404)
    if u.role == "owner":
        p.need("owner")
        if await _owners(s) <= 1:
            raise ApplicationError("last_owner", 409)
    await events.add(s, "user.deleted", "warn", actor=p.actor, params={"name": u.name})
    await s.delete(u)


async def tokens(s: AsyncSession, p: Principal) -> list[TokenOut]:
    st = select(ApiToken).order_by(ApiToken.created_at.desc())
    if p.level() < ROLES["admin"]:
        st = st.where(ApiToken.user_id == as_uuid(p.id))
    return [out(t, TokenOut) for t in (await s.scalars(st)).all()]


async def create_token(s: AsyncSession, p: Principal, data: TokenIn) -> dict:
    p.need("member")
    if data.scope not in ("read", "control"):
        raise ApplicationError("validation", 422, detail="scope")
    if p.scope != "full":
        raise ApplicationError("forbidden", 403)
    raw = f"valo_{new_secret(24)}"
    t = ApiToken(
        user_id=as_uuid(p.id),
        name=data.name,
        token_hash=digest(raw),
        scope=data.scope,
        rooms=data.rooms,
        expires_at=now() + timedelta(days=data.days) if data.days else None,
    )
    s.add(t)
    await s.flush()
    await events.add(s, "token.created", actor=p.actor, params={"name": t.name, "scope": t.scope})
    return {"token": raw, "item": out(t, TokenOut)}


async def delete_token(s: AsyncSession, p: Principal, token_id: str) -> None:
    t = await s.get(ApiToken, as_uuid(token_id))
    if t is None:
        raise ApplicationError("token_not_found", 404)
    if str(t.user_id) != p.id:
        p.need("admin")
    await events.add(s, "token.deleted", "warn", actor=p.actor, params={"name": t.name})
    await s.delete(t)


async def ensure_owner(s: AsyncSession, username: str, name: str, password: str, role: str = "owner") -> User:
    u = await s.scalar(select(User).where(User.username == username.lower()))
    if u is None:
        u = User(
            username=username.lower(),
            name=name,
            password_hash=hash_password(password),
            role=role,
            rooms=[],
            active=True,
        )
        s.add(u)
        await s.flush()
    else:
        u.password_hash, u.role, u.active = hash_password(password), role, True
    return u
