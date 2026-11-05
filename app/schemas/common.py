from datetime import UTC, datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, WithJsonSchema


class Schema(BaseModel):
    """Базовая схема: умеет читать данные прямо из ORM-объектов и dataclass."""

    model_config = ConfigDict(from_attributes=True)


def _utc_without_fraction(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


Timestamp = Annotated[
    datetime,
    PlainSerializer(_utc_without_fraction, return_type=str, when_used="json"),
    WithJsonSchema({"type": "string", "format": "date-time", "examples": ["2026-11-02T09:30:00Z"]}),
]
"""Момент времени в UTC без долей секунды: `2026-11-02T09:30:00Z`.

Стандартный декодер дат в Swift (`.iso8601`) не понимает дробные секунды,
поэтому сервер их не отдаёт.
"""


class ErrorResponse(BaseModel):
    code: str = Field(examples=["not_found"], description="Машиночитаемый код ошибки")
    message: str = Field(examples=["Корзина не найдена"], description="Текст для пользователя")
    request_id: str | None = Field(
        default=None, description="Идентификатор запроса, по нему ищем запись в логах"
    )
    details: Any = Field(default=None, description="Подробности, например ошибки по полям")


class Coordinates(Schema):
    latitude: float = Field(ge=-90, le=90, examples=[60.0087])
    longitude: float = Field(ge=-180, le=180, examples=[30.2582])


def error_responses(*status_codes: int) -> dict[int | str, dict[str, Any]]:
    """Описание ошибок для Swagger, чтобы клиент видел формат ответа при сбое."""
    return {code: {"model": ErrorResponse} for code in status_codes}
