import base64
import hashlib
from functools import cache

from cryptography.fernet import Fernet, InvalidToken

from app.lib import log
from app.lib.settings import env

PREFIX = "enc1:"


@cache
def _box() -> Fernet:
    raw = env("VALO_SECRET_KEY") or env("JWT_SECRET", "change-me")
    key = base64.urlsafe_b64encode(hashlib.sha256(f"valo-secrets:{raw}".encode()).digest())
    return Fernet(key)


def seal(value: str) -> str:
    if not value or value.startswith(PREFIX):
        return value
    return PREFIX + _box().encrypt(value.encode()).decode()


def open_(value: object) -> object:
    if not isinstance(value, str) or not value.startswith(PREFIX):
        return value
    try:
        return _box().decrypt(value[len(PREFIX) :].encode()).decode()
    except InvalidToken:
        log.get("secretbox").error("secret_undecryptable", hint="VALO_SECRET_KEY or JWT_SECRET changed")
        return ""


def derived(purpose: str, length: int = 32) -> str:
    raw = env("VALO_SECRET_KEY") or env("JWT_SECRET", "change-me")
    return hashlib.sha256(f"valo-{purpose}:{raw}".encode()).hexdigest()[:length]
