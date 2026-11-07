import os

import msgspec
from dotenv import load_dotenv

load_dotenv()
load_dotenv(os.environ.get("VALO_SECRETS_FILE", "/secrets/valo.env"), override=False)


def with_password(url: str, password: str) -> str:
    """Вставить пароль в адрес службы, если в адресе есть пользователь без пароля."""
    scheme, sep, rest = url.partition("://")
    if not sep or not password or "@" not in rest:
        return url
    cred, _, host = rest.rpartition("@")
    if ":" in cred:
        return url
    return f"{scheme}://{cred}:{password}@{host}"


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def env_int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


def env_bool(name: str, default: bool = False) -> bool:
    v = os.environ.get(name)
    return default if v is None else v.strip().lower() in ("1", "true", "yes", "on")


class Settings(msgspec.Struct, frozen=True):
    app_env: str = env("APP_ENV", "dev")
    redis_url: str = env("REDIS_URL", "redis://localhost:6379/0")
    rabbitmq_url: str = with_password(
        env("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/"), env("RABBITMQ_PASSWORD")
    )
    mqtt_host: str = env("MQTT_HOST", "localhost")
    mqtt_port: int = env_int("MQTT_PORT", 1883)
    mqtt_user: str = env("MQTT_USER", "valo-core")
    mqtt_password: str = env("MQTT_PASSWORD", "")
    z2m_topic: str = env("Z2M_BASE_TOPIC", "zigbee2mqtt")
    jwt_secret: str = env("JWT_SECRET", "change-me")
    log_level: str = env("LOG_LEVEL", "info")
    log_json: bool = env_bool("LOG_JSON")
    valo_env: str = env("VALO_ENV", "demo" if env_bool("VALO_DEMO") else "real")
    demo: bool = env_bool("VALO_DEMO")
    peers: str = env("VALO_PEERS")
    trusted_proxies: str = env("TRUSTED_PROXIES", "127.0.0.1/32")


def environment() -> dict[str, object]:
    peers = []
    for item in settings.peers.split(","):
        name, _, url = item.strip().partition("=")
        if name and url:
            peers.append({"name": name.strip(), "url": url.strip()})
    return {"name": settings.valo_env, "demo": settings.demo, "peers": peers}


settings = Settings()
