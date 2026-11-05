.PHONY: help install db dev test lint format typecheck check migrate migration seed openapi template up down logs

help:  ## показать список команд
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "} {printf "  make %-12s %s\n", $$1, $$2}'

install:  ## установить зависимости и git-хуки
	uv sync
	uvx pre-commit install

db:  ## запустить PostgreSQL в Docker
	docker compose up -d db

dev:  ## запустить API с автоперезагрузкой на http://localhost:8000
	uv run uvicorn app.main:app --reload --no-access-log

test:  ## запустить тесты с отчётом о покрытии
	uv run pytest --cov --cov-report=term-missing:skip-covered

lint:  ## проверить стиль кода
	uv run ruff check .
	uv run ruff format --check .

format:  ## отформатировать код
	uv run ruff check --fix .
	uv run ruff format .

typecheck:  ## проверить типы
	uv run mypy

check: lint typecheck test  ## всё, что проверяет CI

migrate:  ## применить миграции к локальной БД
	uv run alembic upgrade head

migration:  ## создать миграцию по изменениям моделей: make migration m="описание"
	uv run alembic revision --autogenerate -m "$(m)"

seed:  ## загрузить демонстрационный каталог
	uv run vezzi seed-demo

openapi:  ## обновить docs/openapi.json для iOS-разработчика
	uv run vezzi export-openapi docs/openapi.json

template:  ## обновить Excel-шаблон каталога для команды данных
	uv run vezzi catalog-template docs/catalog_template.xlsx

up:  ## поднять весь стек в Docker (БД, миграции, API)
	docker compose up -d --build

down:  ## остановить стек
	docker compose down

logs:  ## логи API
	docker compose logs -f api
