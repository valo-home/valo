import asyncio
import sys

from app.lib.kv import alive, kv


async def check(name: str) -> bool:
    try:
        return await alive(name)
    finally:
        await kv().aclose()


def main() -> None:
    name = sys.argv[1] if len(sys.argv) > 1 else ""
    if not name:
        sys.exit("python -m app.lib.alive <process>")
    sys.exit(0 if asyncio.run(check(name)) else 1)


if __name__ == "__main__":
    main()
