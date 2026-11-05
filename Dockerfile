# Сборка в два этапа: в первом ставим зависимости через uv, во второй
# переносим только готовое окружение. Итоговый образ меньше и без лишних инструментов.

FROM python:3.13-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY README.md alembic.ini ./
COPY alembic ./alembic
COPY app ./app
RUN uv sync --frozen --no-dev


FROM python:3.13-slim

ARG BUILD_COMMIT=unknown
RUN useradd --create-home --uid 1000 vezzi
WORKDIR /app
COPY --from=builder --chown=vezzi:vezzi /app /app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    BUILD_COMMIT=$BUILD_COMMIT
USER vezzi
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"]

# --proxy-headers: реальный IP клиента берётся из заголовков Caddy (нужно для лимита попыток входа).
# --no-access-log: журнал uvicorn пишет query-строку с координатами; свой журнал ведёт app/core/logging.py.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*", "--no-access-log"]
