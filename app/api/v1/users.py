from fastapi import APIRouter, status

from app.api.deps import CurrentUser, SessionDep, SettingsDep
from app.schemas.auth import ChangePasswordRequest, TokenPair, UserRead
from app.schemas.common import error_responses
from app.services import auth as auth_service

router = APIRouter(prefix="/users", tags=["Аккаунт"], responses=error_responses(401))


@router.get("/me")
def get_me(user: CurrentUser) -> UserRead:
    """Данные текущего пользователя."""
    return UserRead.model_validate(user)


@router.post("/me/password", responses=error_responses(400, 422))
def change_password(
    body: ChangePasswordRequest, user: CurrentUser, session: SessionDep, settings: SettingsDep
) -> TokenPair:
    """Смена пароля. Все остальные устройства выходят из аккаунта, это получает новые токены."""
    tokens = auth_service.change_password(
        session, settings, user, body.current_password, body.new_password
    )
    return TokenPair.model_validate(tokens)


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
def delete_me(user: CurrentUser, session: SessionDep) -> None:
    """Удаление аккаунта вместе с корзинами и планами (требование App Store 5.1.1(v)).

    Действие необратимо. Подтверждение у пользователя запрашивает приложение.
    """
    auth_service.delete_account(session, user)
