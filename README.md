# Vezzi backend

Серверная часть приложения **«Умная корзина»** (рабочее имя Vezzi). Учебный командный проект ИТМО, 2026.

Пользователь iPhone собирает корзину продуктов, а backend находит, где купить всё дешевле с учётом
свежих цен, наличия, лимита магазинов и времени, строит пешеходный маршрут по выбранным магазинам
и сохраняет план, по которому пользователь отмечает покупки прямо в магазине.

- **Swagger (документация API):** `http://localhost:8000/docs` после запуска
- **Спецификация для iOS:** [`docs/openapi.json`](docs/openapi.json), руководство: [`docs/api.md`](docs/api.md)

## Стек

| Задача | Технология |
|---|---|
| Язык и API | Python 3.12+, FastAPI, Pydantic 2 |
| База данных | PostgreSQL 18, SQLAlchemy 2, миграции Alembic |
| Авторизация | JWT (PyJWT), пароли Argon2id (pwdlib), refresh-токены с ротацией |
| Маршруты | OSRM на картах OpenStreetMap (свой сервер) |
| Каталог | импорт Excel (openpyxl), атомарная публикация снимков |
| Качество | pytest (190+ тестов на настоящем PostgreSQL, покрытие 97%), Ruff, mypy, GitHub Actions |
| Запуск | Docker Compose, Caddy (HTTPS), uv |

## Быстрый старт

Нужны [Docker Desktop](https://www.docker.com/products/docker-desktop/) и [uv](https://docs.astral.sh/uv/) (`brew install uv`).

```bash
cp .env.example .env          # локальные настройки
make db                       # PostgreSQL в Docker
uv sync                       # зависимости
make migrate                  # таблицы в БД
make seed                     # демонстрационный каталог: 6 магазинов, 120 товаров
make dev                      # API на http://localhost:8000
```

Откройте http://localhost:8000/docs, зарегистрируйтесь через `POST /api/v1/auth/register`,
нажмите **Authorize** и вставьте `access_token`. Дальше можно создать корзину и посчитать планы.

Без `make` то же самое делается командами из [`Makefile`](Makefile), список: `make help`.

### Настоящие маршруты по Петербургу

По умолчанию локально включён тестовый провайдер маршрутов (`ROUTING_PROVIDER=fake`): он считает по прямой
и честно помечает это в ответе. Чтобы включить настоящие пешеходные маршруты:

```bash
./deploy/osrm/prepare.sh                     # скачать карту и построить граф (~2 минуты)
docker compose --profile routing up -d osrm  # маршрутизатор на localhost:5001
# в .env: ROUTING_PROVIDER=osrm
```

Подробности и замеры: [`docs/routing.md`](docs/routing.md).

## Проверки

Полная репетиция в продакшен-конфигурации: `./deploy/rehearsal.sh <каталог.xlsx>` (см. `docs/deployment.md`).

```bash
make test        # тесты на настоящем PostgreSQL (нужен make db)
make lint        # стиль кода
make typecheck   # типы
make check       # всё вместе, как в CI
```

## Структура

```text
app/
  main.py              сборка приложения FastAPI
  api/                 HTTP-слой: роутеры и зависимости (кто вызывает, с какими правами)
  services/            сценарии: регистрация, корзины, расчёт и сохранённые планы
  planner/             алгоритм планов: чистые функции без БД и сети
  routing/             провайдеры маршрутов: OSRM и тестовый
  catalog_import/      чтение Excel, проверка строк, публикация каталога
  models/              таблицы БД (SQLAlchemy)
  schemas/             форматы запросов и ответов (Pydantic, из них строится Swagger)
  core/                настройки, безопасность, ошибки, логи
  demo/                демонстрационный каталог
  cli.py               команды администратора (uv run vezzi --help)
alembic/               миграции БД
tests/                 unit/: логика, api/: HTTP и БД
deploy/                Caddy, конфигурация сервера, OSRM, резервные копии
docs/                  документация
```

## Документация

| Документ | О чём |
|---|---|
| [`docs/architecture.md`](docs/architecture.md) | Как устроен backend, путь одного запроса, схема БД |
| [`docs/api.md`](docs/api.md) | Руководство для iOS-разработчика: авторизация, ошибки, примеры |
| [`docs/planning.md`](docs/planning.md) | Алгоритм планов, сумма по сетям, округление, формула времени покупок |
| [`docs/reference-check.md`](docs/reference-check.md) | Отчёт сверки расчёта с независимым эталоном |
| [`docs/routing.md`](docs/routing.md) | Почему OSRM: сравнение вариантов и проверка по Петербургу |
| [`docs/catalog-import.md`](docs/catalog-import.md) | Формат Excel для команды данных, разбор черновика |
| [`docs/deployment.md`](docs/deployment.md) | Развёртывание на VPS, HTTPS, резервные копии |
| [`docs/decisions.md`](docs/decisions.md) | Журнал решений и открытые вопросы |

## Команды администратора

```bash
uv run vezzi create-admin --email admin@example.com     # пароль спросит в терминале
uv run vezzi import-catalog catalog.xlsx --show-errors  # загрузить каталог команды
uv run vezzi catalog-template docs/catalog_template.xlsx
uv run vezzi export-openapi docs/openapi.json
```
