from fastapi import APIRouter, Depends, status

from app.api.deps import SessionDep, SettingsDep
from app.core.rate_limit import login_rate_limit, refresh_rate_limit, register_rate_limit
from app.schemas.auth import AuthResponse, Credentials, LoginRequest, RefreshRequest, TokenPair
from app.schemas.common import error_responses
from app.services import auth as auth_service

router = APIRouter(prefix="/auth", tags=["Авторизация"])


@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(register_rate_limit)],
    responses=error_responses(409, 422, 429),
)
def register(body: Credentials, session: SessionDep, settings: SettingsDep) -> AuthResponse:
    """Регистрация по email и паролю. Сразу возвращает токены, отдельно входить не нужно."""
    user, tokens = auth_service.register(session, settings, body.email, body.password)
    return AuthResponse.model_validate({"user": user, "tokens": tokens})


@router.post(
    "/login", dependencies=[Depends(login_rate_limit)], responses=error_responses(401, 422, 429)
)
def login(body: LoginRequest, session: SessionDep, settings: SettingsDep) -> AuthResponse:
    """Вход по email и паролю. Каждый вход создаёт отдельную сессию устройства."""
    user, tokens = auth_service.login(session, settings, body.email, body.password)
    return AuthResponse.model_validate({"user": user, "tokens": tokens})


@router.post(
    "/refresh", dependencies=[Depends(refresh_rate_limit)], responses=error_responses(401, 429)
)
def refresh(body: RefreshRequest, session: SessionDep, settings: SettingsDep) -> TokenPair:
    """Новая пара токенов в обмен на refresh-токен.

    Refresh-токен одноразовый: после обмена старый перестаёт работать.
    Повторное использование старого токена завершает сессию устройства.
    Клиент не должен отправлять два обновления одновременно.
    """
    tokens = auth_service.refresh(session, settings, body.refresh_token)
    return TokenPair.model_validate(tokens)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(body: RefreshRequest, session: SessionDep) -> None:
    """Выход на этом устройстве: refresh-токен отзывается. Повторный вызов безопасен."""
    auth_service.logout(session, body.refresh_token)
