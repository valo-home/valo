import hashlib
import secrets
import time

import jwt
from pwdlib import PasswordHash

from app.lib.settings import settings

_hasher = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return _hasher.verify(password, hashed)
    except Exception:
        return False


def make_jwt(sub: str, kind: str, ttl: int, **extra) -> str:
    now = int(time.time())
    return jwt.encode({"sub": sub, "kind": kind, "iat": now, "exp": now + ttl, **extra}, settings.jwt_secret, "HS256")


def read_jwt(token: str, kind: str) -> dict | None:
    try:
        data = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    return data if data.get("kind") == kind else None


def new_secret(size: int = 24) -> str:
    return secrets.token_urlsafe(size)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()
