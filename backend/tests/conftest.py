import os

os.environ["APP_ENV"] = "test"
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://valo:valo@localhost:5432/valo_test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
os.environ.setdefault("JWT_SECRET", "test-secret-test-secret-test-secret-42")
os.environ.setdefault("EXT_CATALOG", os.path.join(os.path.dirname(__file__), "..", "..", "extensions", "catalog.json"))
os.environ.setdefault("EXT_SDK_PATH", os.path.join(os.path.dirname(__file__), "..", "..", "extensions", "sdk"))
os.environ.setdefault("EXT_DIR", "/tmp/valo-test-extensions")

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest

from app.db.base import Base, config
from app.lib import kv as kvmod
from app.lib import mqtt, realtime


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def published(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, Any]]:
    sent: list[tuple[str, Any]] = []

    async def fake(topic: str, payload: Any = None, qos: int = 0, retain: bool = False, properties: Any = None) -> None:
        sent.append((topic, payload))

    monkeypatch.setattr(mqtt, "publish", fake)
    return sent


@pytest.fixture
async def client(published: list) -> AsyncIterator[httpx.AsyncClient]:
    from app.server.app import app

    engine = config.get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    await kvmod.kv().flushdb()
    async with app.lifespan(), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c
    await engine.dispose()
    await kvmod.kv().aclose()
    kvmod._client = None
    realtime._mgr = None


@pytest.fixture
async def owner(client: httpx.AsyncClient) -> dict[str, str]:
    r = await client.post(
        "/api/v1/setup",
        json={
            "owner": {"username": "mikko", "name": "Mikko Virtanen", "password": "secret123"},
            "home": {"name": "Home", "lat": 60.205, "lon": 24.655, "timezone": "Europe/Helsinki"},
        },
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}
