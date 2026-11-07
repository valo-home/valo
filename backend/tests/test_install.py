import pathlib

import httpx
import pytest

from app.domain import coordinator
from app.lib import bootstrap
from app.lib.settings import with_password

pytestmark = pytest.mark.anyio


def test_secrets_keep_given_then_stored_then_new(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VALO_SECRETS", str(tmp_path))
    for k in bootstrap.KEYS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("POSTGRES_PASSWORD", "fromenv")
    bootstrap.main()
    first = bootstrap.parse((tmp_path / "valo.env").read_text())
    assert first["POSTGRES_PASSWORD"] == "fromenv" and len(first["JWT_SECRET"]) == 32
    assert (tmp_path / "postgres_password").read_text() == "fromenv"
    assert (tmp_path / "mqtt_password").read_text() == first["MQTT_PASSWORD"]
    monkeypatch.delenv("POSTGRES_PASSWORD")
    bootstrap.main()
    again = bootstrap.parse((tmp_path / "valo.env").read_text())
    assert again == first
    assert bootstrap.generate() != bootstrap.generate() and bootstrap.generate().isalnum()


def test_service_urls_get_the_password() -> None:
    assert with_password("postgresql+asyncpg://valo@postgres:5432/valo", "pw") == (
        "postgresql+asyncpg://valo:pw@postgres:5432/valo"
    )
    assert with_password("amqp://valo:old@rabbitmq:5672/", "new") == "amqp://valo:old@rabbitmq:5672/"
    assert with_password("redis://redis:6379/0", "pw") == "redis://redis:6379/0"
    assert with_password("amqp://valo@rabbitmq:5672/", "") == "amqp://valo@rabbitmq:5672/"


def test_coordinator_guess_and_names() -> None:
    v2 = "usb-Itead_Sonoff_Zigbee_3.0_USB_Dongle_Plus_V2_dee7a2833c4aef11a8bbbea079f42d1b-if00-port0"
    assert coordinator.guess(v2) == "ember"
    assert coordinator.guess("usb-ITead_Sonoff_Zigbee_3.0_USB_Dongle_Plus_2a4b-if00-port0") == "zstack"
    assert coordinator.guess("usb-dresden_elektronik_ConBee_II_DE1-if00") == "deconz"
    assert coordinator.guess("usb-FTDI_FT232R_USB_UART_A1-if00-port0") == ""
    assert coordinator.pretty(v2) == "Itead Sonoff Zigbee 3.0 USB Dongle Plus V2"


async def test_adapter_is_chosen_in_setup_only_before_owner(
    client: httpx.AsyncClient, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dev = tmp_path / "dev" / "serial" / "by-id"
    dev.mkdir(parents=True)
    name = "usb-Itead_Sonoff_Zigbee_3.0_USB_Dongle_Plus_V2_abc0123456789abc-if00-port0"
    (dev / name).write_text("")
    conf = tmp_path / "zconf" / "adapter.env"
    monkeypatch.setenv("HOST_DEV", str(tmp_path / "dev"))
    monkeypatch.setenv("ZIGBEE_CONF", str(conf))
    monkeypatch.delenv("ZIGBEE_ADAPTER", raising=False)
    r = await client.get("/api/v1/setup/adapters")
    assert r.status_code == 200 and r.json()["adapters"][0]["type"] == "ember" and r.json()["current"] is None
    path = f"/dev/serial/by-id/{name}"
    bad = await client.post("/api/v1/setup/adapter", json={"path": "/dev/sda", "type": "ember"})
    assert bad.status_code == 422
    assert (await client.post("/api/v1/setup/adapter", json={"path": path, "type": "magic"})).status_code == 422
    r = await client.post("/api/v1/setup/adapter", json={"path": path, "type": "ember"})
    assert r.status_code == 200 and r.json()["current"] == {"path": path, "type": "ember", "source": "ui"}
    assert conf.read_text() == f"port={path}\nadapter=ember\n"
    monkeypatch.setenv("ZIGBEE_ADAPTER", "/dev/ttyUSB9")
    r = await client.post("/api/v1/setup/adapter", json={"path": path, "type": "ember"})
    assert r.status_code == 409


async def test_setup_adapter_is_closed_after_owner(client: httpx.AsyncClient, owner: dict) -> None:
    assert (await client.get("/api/v1/setup/adapters")).status_code == 409
    assert (await client.get("/api/v1/zigbee/adapter", headers=owner)).status_code == 200
    assert (await client.get("/api/v1/zigbee/adapter")).status_code == 401
