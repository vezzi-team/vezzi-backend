"""Настройки приложения. Читаются из переменных окружения и файла .env."""

from functools import lru_cache
from typing import Literal, Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: Literal["local", "test", "production"] = "local"
    log_level: str = "INFO"
    docs_enabled: bool = True

    database_url: str = "postgresql+psycopg://vezzi:vezzi@localhost:5432/vezzi"

    jwt_secret_key: SecretStr = SecretStr("change-me-in-env-file-at-least-32-chars")
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = Field(default=30, ge=1)
    refresh_token_ttl_days: int = Field(default=30, ge=1)
    auth_rate_limit_per_minute: int = Field(default=10, ge=1)

    # По ТЗ (F04) порог 6 часов, руководитель позже утвердил 24 часа. См. docs/decisions.md.
    offer_max_age_hours: int = Field(default=24, ge=1)
    catalog_timezone: str = "Europe/Moscow"
    max_upload_size_mb: int = Field(default=20, ge=1)

    # Коммит, из которого собран образ. Задаётся при сборке, см. docs/deployment.md.
    build_commit: str = "dev"

    routing_provider: Literal["osrm", "fake"] = "fake"
    routing_timeout_seconds: float = Field(default=10.0, gt=0)
    osrm_base_url: str = "http://localhost:5001"

    planner_candidate_stores: int = Field(default=8, ge=1, le=15)
    shopping_min_visit_seconds: int = Field(default=600, ge=0)
    shopping_base_seconds: int = Field(default=300, ge=0)
    shopping_seconds_per_position: int = Field(default=60, ge=0)
    shopping_seconds_per_unit: int = Field(default=5, ge=0)

    @model_validator(mode="after")
    def check_production_safety(self) -> Self:
        if self.environment != "production":
            return self
        if len(self.jwt_secret_key.get_secret_value()) < 32 or "change-me" in (
            self.jwt_secret_key.get_secret_value()
        ):
            raise ValueError("В production нужен свой JWT_SECRET_KEY длиной от 32 символов")
        if self.routing_provider == "fake":
            raise ValueError("В production нельзя использовать ROUTING_PROVIDER=fake")
        return self

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
