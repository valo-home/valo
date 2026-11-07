import re
import secrets
import uuid
from datetime import datetime
from typing import Any

import msgspec
from sqlalchemy import and_, or_

from app.lib.errors import ApplicationError


def cursor(raw: str | None) -> tuple[datetime, uuid.UUID | None] | None:
    """Курсор постраничного вывода вида время|id. id нужен, чтобы не терять записи с одинаковым временем."""
    if not raw:
        return None
    ts, _, rid = raw.partition("|")
    try:
        return datetime.fromisoformat(ts), uuid.UUID(rid) if rid else None
    except ValueError as e:
        raise ApplicationError("validation", 422, detail="before") from e


def after_cursor(col: Any, idcol: Any, cur: tuple[datetime, uuid.UUID | None]) -> Any:
    ts, rid = cur
    return col < ts if rid is None else or_(col < ts, and_(col == ts, idcol < rid))


ROLES = {"guest": 0, "member": 1, "admin": 2, "owner": 3}
_TR = str.maketrans(
    {
        **dict(zip("абвгдезийклмнопрстуфхыэ", "abvgdezijklmnoprstufhye", strict=True)),
        "ж": "zh",
        "ц": "ts",
        "ч": "ch",
        "ш": "sh",
        "щ": "sch",
        "ю": "yu",
        "я": "ya",
        "ь": "",
        "ъ": "",
        "ё": "e",
        "є": "ye",
        "і": "i",
        "ї": "yi",
        "ґ": "g",
        "ä": "a",
        "ö": "o",
        "å": "a",
    }
)


class S(msgspec.Struct, rename="camel"):
    pass


class Principal(S, frozen=True):
    id: str
    username: str
    name: str
    role: str
    rooms: list[str] = []
    scope: str = "full"

    @property
    def actor(self) -> str:
        return f"user:{self.username}"

    def level(self) -> int:
        return min(ROLES.get(self.role, 0), {"read": 0, "control": 1}.get(self.scope, 3))

    def need(self, role: str) -> None:
        if self.level() < ROLES[role]:
            raise ApplicationError("forbidden", 403)

    def room_ok(self, room: str | None) -> bool:
        return not self.rooms or room in self.rooms

    def need_room(self, room: str | None) -> None:
        if not self.room_ok(room):
            raise ApplicationError("forbidden", 403)


SYSTEM = Principal(id="system", username="system", name="system", role="owner")


def out[T](obj: Any, kind: type[T]) -> T:
    return msgspec.convert(obj, kind, from_attributes=True)


def patch(target: Any, data: S, allowed: set[str] | None = None) -> dict[str, Any]:
    changed = {}
    for f in data.__struct_fields__:
        v = getattr(data, f)
        if v is msgspec.UNSET or (allowed is not None and f not in allowed):
            continue
        if getattr(target, f) != v:
            setattr(target, f, v)
            changed[f] = v
    return changed


def slug(text: str, fallback: str = "x") -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower().translate(_TR)).strip("-")[:48]
    return s or f"{fallback}-{secrets.token_hex(3)}"


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def as_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as e:
        raise ApplicationError("not_found", 404) from e


Unset = msgspec.UnsetType
UNSET = msgspec.UNSET
