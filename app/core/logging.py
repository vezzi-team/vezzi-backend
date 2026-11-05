"""Логирование и middleware, которое пишет одну строку на каждый запрос.

В лог попадают метод, путь, статус, длительность и request_id.
Query-параметры не пишем: там бывают координаты пользователя (требование N03).
"""

import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse

from app.core.errors import error_body
from app.core.request_context import get_request_id, set_request_id

logger = logging.getLogger("app.requests")

REQUEST_ID_HEADER = "X-Request-ID"
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id() or "-"
        return True


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler()
    handler.addFilter(RequestIdFilter())
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s")
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    # httpx2 пишет в INFO полный URL запроса, а в запросах к OSRM есть координаты пользователя.
    logging.getLogger("httpx2").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


async def request_context_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    incoming = request.headers.get(REQUEST_ID_HEADER, "")
    request_id = incoming if _VALID_REQUEST_ID.match(incoming) else uuid.uuid4().hex
    set_request_id(request_id)

    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("Необработанная ошибка: %s %s", request.method, request.url.path)
        response = JSONResponse(
            error_body("internal_error", "Внутренняя ошибка сервера"), status_code=500
        )

    duration_ms = (time.perf_counter() - started) * 1000
    response.headers[REQUEST_ID_HEADER] = request_id
    # JSON всегда в UTF-8, но без явного charset браузер на русской системе
    # может прочитать ответ как Windows-1251 и показать «кракозябры».
    if response.headers.get("content-type") == "application/json":
        response.headers["content-type"] = "application/json; charset=utf-8"
    logger.info(
        "%s %s -> %s (%.1f ms)",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
    )
    return response
