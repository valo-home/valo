import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from advanced_alchemy.base import DefaultBase
from advanced_alchemy.extensions.litestar import AsyncSessionConfig, EngineConfig, SQLAlchemyAsyncConfig
from advanced_alchemy.types import DateTimeUTC, JsonB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.lib import log
from app.lib.settings import env, with_password

DATABASE_URL = with_password(
    env("DATABASE_URL", "postgresql+asyncpg://valo:valo@localhost:5432/valo"), env("POSTGRES_PASSWORD")
)
_log = log.get("db")


def now() -> datetime:
    return datetime.now(UTC)


class Base(DefaultBase):
    __abstract__ = True


class Stamped:
    created_at: Mapped[datetime] = mapped_column(DateTimeUTC(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTimeUTC(timezone=True), default=now, onupdate=now)


def uid() -> uuid.UUID:
    return uuid.uuid7()


config = SQLAlchemyAsyncConfig(
    connection_string=DATABASE_URL,
    session_config=AsyncSessionConfig(expire_on_commit=False),
    engine_config=EngineConfig(pool_pre_ping=True, pool_size=10, max_overflow=10),
    before_send_handler=None,
    enable_touch_updated_timestamp_listener=False,
)


def session():
    return config.get_session()


def after(s: AsyncSession, fn: Callable[[], Awaitable[None]]) -> None:
    s.info.setdefault("after_commit", []).append(fn)


@asynccontextmanager
async def savepoint(s: AsyncSession) -> AsyncIterator[None]:
    """Вложенная транзакция. При откате отбрасываются и действия после фиксации, добавленные внутри нее."""
    mark = len(s.info.get("after_commit", []))
    try:
        async with s.begin_nested():
            yield
    except BaseException:
        del s.info.setdefault("after_commit", [])[mark:]
        raise


async def commit(s: AsyncSession) -> None:
    await s.commit()
    for fn in s.info.pop("after_commit", []):
        try:
            await fn()
        except Exception as e:
            _log.error("after_commit_failed", fn=getattr(fn, "__qualname__", str(fn)), error=str(e), exc_info=True)


async def rollback(s: AsyncSession) -> None:
    s.info.pop("after_commit", None)
    await s.rollback()


__all__ = ["Base", "DateTimeUTC", "JsonB", "Stamped", "after", "commit", "config", "now", "rollback", "session", "uid"]
