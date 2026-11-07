"""Разовая начальная настройка установки: секреты служб в общем томе.

Запускается службой init перед остальными. Значение берется из переменной окружения, если она задана
(файл среды ./valo), иначе остается прежнее из тома, иначе создается случайное. Поэтому установка через
одну команду docker compose up работает без файла переменных, а существующая среда сохраняет свои пароли.
"""

import os
import pathlib
import secrets
import string

KEYS = (
    "POSTGRES_PASSWORD",
    "RABBITMQ_PASSWORD",
    "JWT_SECRET",
    "MQTT_PASSWORD",
    "Z2M_MQTT_PASSWORD",
    "MOCKS_MQTT_PASSWORD",
)
FILES = {
    "POSTGRES_PASSWORD": "postgres_password",
    "RABBITMQ_PASSWORD": "rabbitmq_password",
    "MQTT_PASSWORD": "mqtt_password",
    "Z2M_MQTT_PASSWORD": "z2m_mqtt_password",
    "MOCKS_MQTT_PASSWORD": "mocks_mqtt_password",
}
ALPHABET = string.ascii_letters + string.digits


def generate(n: int = 32) -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(n))


def parse(text: str) -> dict[str, str]:
    out = {}
    for line in text.splitlines():
        k, sep, v = line.partition("=")
        if sep and k.strip() and not k.lstrip().startswith("#"):
            out[k.strip()] = v.strip()
    return out


def resolve(env: dict[str, str], old: dict[str, str]) -> dict[str, str]:
    """Значения секретов: заданное в окружении, иначе прежнее, иначе новое случайное."""
    return {k: (env.get(k) or "").strip() or old.get(k) or generate() for k in KEYS}


def write(base: pathlib.Path, values: dict[str, str]) -> list[str]:
    base.mkdir(parents=True, exist_ok=True)
    main = base / "valo.env"
    tmp = base / ".valo.env.tmp"
    tmp.write_text("".join(f"{k}={values[k]}\n" for k in KEYS))
    tmp.chmod(0o644)
    tmp.replace(main)
    for key, name in FILES.items():
        f = base / name
        f.write_text(values[key])
        f.chmod(0o644)
    return sorted(values)


def main() -> None:
    base = pathlib.Path(os.environ.get("VALO_SECRETS", "/secrets"))
    main_file = base / "valo.env"
    old = parse(main_file.read_text()) if main_file.is_file() else {}
    given = sorted(k for k in KEYS if (os.environ.get(k) or "").strip())
    fresh = sorted(k for k in KEYS if not (os.environ.get(k) or "").strip() and not old.get(k))
    write(base, resolve(dict(os.environ), old))
    print(f"secrets ready in {base}: from environment {given or '-'}, created {fresh or '-'}", flush=True)


if __name__ == "__main__":
    main()
