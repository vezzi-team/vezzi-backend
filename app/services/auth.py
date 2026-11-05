"""Регистрация, вход, обновление токенов, выход, смена пароля и удаление аккаунта."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import AppError, AuthenticationError, ConflictError
from app.core.security import (
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)
from app.models import RefreshSession, User


@dataclass(frozen=True)
class IssuedTokens:
    access_token: str
    refresh_token: str
    expires_in: int


def normalize_email(email: str) -> str:
    return email.strip().lower()


def register(
    session: Session, settings: Settings, email: str, password: str
) -> tuple[User, IssuedTokens]:
    user = User(email=normalize_email(email), password_hash=hash_password(password))
    session.add(user)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError("Этот email уже зарегистрирован", code="email_taken") from exc
    tokens = _start_session(session, settings, user.id)
    session.commit()
    return user, tokens


def login(
    session: Session, settings: Settings, email: str, password: str
) -> tuple[User, IssuedTokens]:
    user = session.scalar(select(User).where(User.email == normalize_email(email)))
    # Пароль проверяем даже для несуществующего email, чтобы время ответа было одинаковым.
    password_ok = verify_password(password, user.password_hash if user else None)
    if user is None or not password_ok:
        raise AuthenticationError("Неверный email или пароль", code="invalid_credentials")
    tokens = _start_session(session, settings, user.id)
    session.commit()
    return user, tokens


def refresh(session: Session, settings: Settings, refresh_token: str) -> IssuedTokens:
    now = datetime.now(UTC)
    current = session.scalar(
        select(RefreshSession)
        .where(RefreshSession.token_hash == hash_refresh_token(refresh_token))
        .with_for_update()
    )
    if current is None:
        raise AuthenticationError("Сессия не найдена, войдите заново", code="invalid_refresh_token")
    if current.revoked_at is not None:
        _revoke_family(session, current.family_id, now)
        session.commit()
        raise AuthenticationError(
            "Этот токен уже использовался. Войдите заново", code="refresh_token_reused"
        )
    if current.expires_at <= now:
        raise AuthenticationError("Сессия истекла, войдите заново", code="refresh_token_expired")

    current.revoked_at = now
    tokens = _start_session(session, settings, current.user_id, family_id=current.family_id)
    session.commit()
    return tokens


def logout(session: Session, refresh_token: str) -> None:
    current = session.scalar(
        select(RefreshSession).where(RefreshSession.token_hash == hash_refresh_token(refresh_token))
    )
    if current is not None:
        _revoke_family(session, current.family_id, datetime.now(UTC))
        session.commit()


def change_password(
    session: Session, settings: Settings, user: User, current_password: str, new_password: str
) -> IssuedTokens:
    if not verify_password(current_password, user.password_hash):
        raise AppError("Текущий пароль указан неверно", code="wrong_password")
    user.password_hash = hash_password(new_password)
    session.execute(
        update(RefreshSession)
        .where(RefreshSession.user_id == user.id, RefreshSession.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
    tokens = _start_session(session, settings, user.id)
    session.commit()
    return tokens


def delete_account(session: Session, user: User) -> None:
    """Удаляет пользователя. Корзины, планы и сессии удаляются каскадно (Apple 5.1.1(v))."""
    session.delete(user)
    session.commit()


def _start_session(
    session: Session, settings: Settings, user_id: uuid.UUID, family_id: uuid.UUID | None = None
) -> IssuedTokens:
    refresh_token = generate_refresh_token()
    session.add(
        RefreshSession(
            user_id=user_id,
            family_id=family_id or uuid.uuid4(),
            token_hash=hash_refresh_token(refresh_token),
            expires_at=datetime.now(UTC) + timedelta(days=settings.refresh_token_ttl_days),
        )
    )
    access = create_access_token(user_id, settings)
    return IssuedTokens(access.token, refresh_token, access.expires_in)


def _revoke_family(session: Session, family_id: uuid.UUID, now: datetime) -> None:
    session.execute(
        update(RefreshSession)
        .where(RefreshSession.family_id == family_id, RefreshSession.revoked_at.is_(None))
        .values(revoked_at=now)
    )
