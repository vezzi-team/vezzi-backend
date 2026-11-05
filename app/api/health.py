from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app import __version__
from app.api.deps import SessionDep, SettingsDep

router = APIRouter(tags=["Служебное"])


@router.get("/health")
def health() -> dict[str, str]:
    """Процесс жив. Используется Docker и мониторингом."""
    return {"status": "ok"}


@router.get("/version")
def version(settings: SettingsDep) -> dict[str, str]:
    """Какая сборка сейчас работает: версия и коммит."""
    return {"version": __version__, "commit": settings.build_commit}


@router.get("/ready", responses={503: {"description": "База данных недоступна"}})
def ready(session: SessionDep) -> JSONResponse:
    """Сервис готов принимать запросы: база данных отвечает."""
    try:
        session.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return JSONResponse({"status": "unavailable", "database": "error"}, status_code=503)
    return JSONResponse({"status": "ok", "database": "ok"})
