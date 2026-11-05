"""Единый формат ошибок API: {"code", "message", "request_id", "details"}.

Сервисы бросают наследников AppError, а обработчики ниже превращают их в JSON.
Так бизнес-логика не знает про HTTP, а клиент всегда получает одинаковую структуру.
"""

import logging
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.request_context import get_request_id

logger = logging.getLogger(__name__)


class AppError(Exception):
    status_code: int = 400
    code: str = "bad_request"
    message: str = "Некорректный запрос"

    def __init__(
        self, message: str | None = None, *, code: str | None = None, details: Any = None
    ) -> None:
        self.message = message or self.message
        self.code = code or self.code
        self.details = details
        super().__init__(self.message)


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"
    message = "Объект не найден"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"
    message = "Конфликт с текущим состоянием данных"


class AuthenticationError(AppError):
    status_code = 401
    code = "not_authenticated"
    message = "Требуется вход в аккаунт"


class PermissionDeniedError(AppError):
    status_code = 403
    code = "permission_denied"
    message = "Недостаточно прав"


class BusinessRuleError(AppError):
    status_code = 422
    code = "business_rule_violation"
    message = "Запрос нарушает правила приложения"


class RateLimitedError(AppError):
    status_code = 429
    code = "rate_limited"
    message = "Слишком много запросов, попробуйте позже"


class ServiceUnavailableError(AppError):
    status_code = 503
    code = "service_unavailable"
    message = "Сервис временно недоступен"


def error_body(code: str, message: str, details: Any = None) -> dict[str, Any]:
    body: dict[str, Any] = {"code": code, "message": message, "request_id": get_request_id()}
    if details is not None:
        body["details"] = details
    return body


# Эти ошибки формирует сам FastAPI, поэтому по умолчанию они на английском.
FRAMEWORK_MESSAGES = {
    404: "Такого адреса нет",
    405: "Этот адрес не принимает такой запрос",
}


async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
    headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
    return JSONResponse(
        error_body(exc.code, exc.message, exc.details), status_code=exc.status_code, headers=headers
    )


async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    details = [
        {"field": ".".join(str(part) for part in error["loc"]), "message": error["msg"]}
        for error in exc.errors()
    ]
    return JSONResponse(
        error_body("validation_error", "Проверьте введённые данные", details), status_code=422
    )


async def handle_http_exception(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    status = HTTPStatus(exc.status_code)
    code = status.phrase.lower().replace(" ", "_")
    message = FRAMEWORK_MESSAGES.get(exc.status_code, str(exc.detail))
    return JSONResponse(error_body(code, message), status_code=exc.status_code, headers=exc.headers)


def register_error_handlers(app: FastAPI) -> None:
    app.exception_handler(AppError)(handle_app_error)
    app.exception_handler(RequestValidationError)(handle_validation_error)
    app.exception_handler(StarletteHTTPException)(handle_http_exception)
