"""Точка входа: сборка FastAPI-приложения.

Запуск для разработки: `uv run uvicorn app.main:app --reload`
Документация API (Swagger): http://localhost:8000/docs
"""

from fastapi import FastAPI
from fastapi.routing import APIRoute

from app import __version__
from app.api import health
from app.api.v1 import api_router
from app.core.config import get_settings
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging, request_context_middleware

DESCRIPTION = """
Backend приложения **«Умная корзина»** (Vezzi): корзины, сравнение цен
в магазинах, пешеходный маршрут и сохранённые планы покупки.

**Как авторизоваться в Swagger**
1. Вызовите `POST /api/v1/auth/register` или `POST /api/v1/auth/login`.
2. Скопируйте `tokens.access_token` из ответа.
3. Нажмите **Authorize** справа вверху и вставьте токен.

**Общие правила**
- Деньги в целых копейках (`8999` = 89,99 ₽), время в секундах, расстояния в метрах.
- Время в ответах: UTC без долей секунды, `2026-11-02T09:30:00Z` (подходит для `.iso8601` в Swift).
- Любая ошибка приходит в формате `{"code", "message", "request_id", "details"}`.
"""

TAGS = [
    {"name": "Авторизация", "description": "Регистрация, вход и обновление токенов"},
    {"name": "Аккаунт", "description": "Текущий пользователь, смена пароля, удаление аккаунта"},
    {"name": "Каталог", "description": "Товары, цены и магазины пилота"},
    {"name": "Корзины", "description": "Корзины пользователя и расчёт планов покупки"},
    {"name": "Планы покупки", "description": "Выбор плана, отметки в магазине и история"},
    {"name": "Администрирование", "description": "Загрузка каталога (только роль admin)"},
    {"name": "Служебное", "description": "Проверки работоспособности"},
]


def _operation_id(route: APIRoute) -> str:
    """operationId = имя функции: в iOS-клиенте, сгенерированном по OpenAPI, понятные методы."""
    return route.name


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title="Vezzi API",
        version=__version__,
        description=DESCRIPTION,
        openapi_tags=TAGS,
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url="/redoc" if settings.docs_enabled else None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
        generate_unique_id_function=_operation_id,
    )
    app.middleware("http")(request_context_middleware)
    register_error_handlers(app)
    app.include_router(health.router)
    app.include_router(api_router)
    return app


app = create_app()
