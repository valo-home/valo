import asyncio
import json
import logging
import os
import pathlib
import sys
from typing import Any

from valo_mocks import llm, seed, sim

log = logging.getLogger("mocks")


def secrets_env(path: str = "/secrets/valo.env") -> None:
    """Секреты из тома начальной настройки. Заданные в окружении значения не заменяются."""
    f = pathlib.Path(os.environ.get("VALO_SECRETS_FILE", path))
    if not f.is_file():
        return
    for line in f.read_text().splitlines():
        k, sep, v = line.partition("=")
        if sep and k.strip() and not os.environ.get(k.strip()):
            os.environ[k.strip()] = v.strip()
    url = os.environ.get("DATABASE_URL", "")
    pw = os.environ.get("POSTGRES_PASSWORD", "")
    scheme, _, rest = url.partition("://")
    if pw and "@" in rest and ":" not in rest.rpartition("@")[0]:
        cred, _, host = rest.rpartition("@")
        os.environ["DATABASE_URL"] = f"{scheme}://{cred}:{pw}@{host}"


secrets_env()


def scenario() -> dict[str, Any]:
    path = os.environ.get("MOCKS_SCENARIO") or pathlib.Path(__file__).with_name("scenario.json")
    return json.loads(pathlib.Path(path).read_text("utf-8"))


async def both(sc: dict[str, Any]) -> None:
    async def seeding() -> None:
        try:
            await seed.run(sc)
        except Exception:
            log.exception("seed failed")

    await asyncio.gather(sim.Sim(sc).run(), seeding(), llm.serve(int(os.environ.get("MOCKS_LLM_PORT", "8090"))))


async def ctl(args: list[str]) -> None:
    body: dict[str, Any] = {"device": args[0], "state": {}}
    for pair in args[1:]:
        k, _, v = pair.partition("=")
        try:
            val = json.loads(v)
        except ValueError:
            val = v
        if k == "online":
            body["online"] = val
        else:
            body["state"][k] = val
    async with sim.client() as c:
        await c.publish(sim.CTL, json.dumps(body), qos=1)
    log.info("sent %s", body)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"
    if cmd == "run":
        asyncio.run(sim.Sim(scenario()).run())
    elif cmd == "seed":
        asyncio.run(seed.run(scenario()))
    elif cmd == "all":
        asyncio.run(both(scenario()))
    elif cmd == "ctl" and len(sys.argv) > 2:
        asyncio.run(ctl(sys.argv[2:]))
    else:
        sys.exit("python -m valo_mocks [all|run|seed|ctl <device> key=value ...]")


if __name__ == "__main__":
    main()
