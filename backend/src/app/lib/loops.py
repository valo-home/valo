"""Фоновые циклы процессов, которые переживают временные сбои Redis, базы или сети."""

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any


async def forever(name: str, fn: Callable[[], Awaitable[None]], log: Any, pause: float = 3.0) -> None:
    """Запускать fn снова после ошибки или выхода. Пауза растет до минуты и сбрасывается после минуты работы."""
    delay = pause
    while True:
        started = time.monotonic()
        try:
            await fn()
            log.warning("loop_exited", loop=name)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.error("loop_failed", loop=name, error=str(e), exc_info=True)
        if time.monotonic() - started > 60:
            delay = pause
        await asyncio.sleep(delay)
        delay = min(delay * 2, 60.0)
