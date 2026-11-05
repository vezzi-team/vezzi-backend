"""Ограничение частоты запросов к входу и регистрации (защита от перебора паролей).

Счётчики живут в памяти процесса. Если запустить несколько воркеров uvicorn,
у каждого будет свой счётчик. Для учебного стенда этого достаточно; в большом
проекте лимиты переносят в Redis или в reverse proxy.
"""

import threading
import time
from collections import defaultdict, deque
from typing import ClassVar

from fastapi import Request

from app.core.config import get_settings
from app.core.errors import RateLimitedError


class RateLimit:
    """FastAPI-зависимость: не больше N запросов за окно на один IP-адрес."""

    _instances: ClassVar[list["RateLimit"]] = []

    def __init__(self, scope: str, window_seconds: int = 60) -> None:
        self.scope = scope
        self.window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()
        RateLimit._instances.append(self)

    def __call__(self, request: Request) -> None:
        limit = get_settings().auth_rate_limit_per_minute
        client = request.client.host if request.client else "unknown"
        now = time.monotonic()
        with self._lock:
            hits = self._hits[client]
            while hits and now - hits[0] > self.window_seconds:
                hits.popleft()
            if len(hits) >= limit:
                retry_after = int(self.window_seconds - (now - hits[0])) + 1
                raise RateLimitedError(details={"retry_after_seconds": retry_after})
            hits.append(now)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()

    @classmethod
    def reset_all(cls) -> None:
        for instance in cls._instances:
            instance.reset()


login_rate_limit = RateLimit("login")
register_rate_limit = RateLimit("register")
refresh_rate_limit = RateLimit("refresh")
