"""Зависимости FastAPI: сессия БД, настройки, текущий пользователь, маршрутизатор."""

from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import AuthenticationError, PermissionDeniedError
from app.core.security import InvalidTokenError, decode_access_token
from app.db.session import get_session
from app.models import User
from app.routing import RoutingProvider, get_routing_provider

_bearer = HTTPBearer(auto_error=False, description="Access-токен из /auth/login")

SessionDep = Annotated[Session, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
RoutingDep = Annotated[RoutingProvider, Depends(get_routing_provider)]


def get_current_user(
    session: SessionDep,
    settings: SettingsDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    if credentials is None:
        raise AuthenticationError()
    try:
        user_id = decode_access_token(credentials.credentials, settings)
    except InvalidTokenError as exc:
        raise AuthenticationError("Токен недействителен или истёк", code="invalid_token") from exc
    user = session.get(User, user_id)
    if user is None:
        raise AuthenticationError("Аккаунт не найден", code="invalid_token")
    return user


def get_admin_user(user: Annotated[User, Depends(get_current_user)]) -> User:
    if not user.is_admin:
        raise PermissionDeniedError("Действие доступно только администратору")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
AdminUser = Annotated[User, Depends(get_admin_user)]
