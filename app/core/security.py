"""Пароли, access-токены (JWT) и refresh-токены.

- Пароль хранится только как хеш Argon2id (с солью внутри хеша).
- Access-токен: короткоживущий JWT, подписанный секретом сервера.
- Refresh-токен: случайная строка. В БД лежит только её SHA-256,
  поэтому утечка базы не даёт готовых токенов.
"""

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from pwdlib import PasswordHash

from app.core.config import Settings

_password_hash = PasswordHash.recommended()

# Хеш случайного пароля. Проверяем его, когда пользователя с таким email нет,
# чтобы время ответа не выдавало, зарегистрирован ли email.
_DUMMY_PASSWORD_HASH = _password_hash.hash(secrets.token_urlsafe(16))


def hash_password(password: str) -> str:
    return _password_hash.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    if password_hash is None:
        _password_hash.verify(password, _DUMMY_PASSWORD_HASH)
        return False
    return _password_hash.verify(password, password_hash)


@dataclass(frozen=True)
class AccessToken:
    token: str
    expires_in: int


class InvalidTokenError(Exception):
    pass


def create_access_token(user_id: uuid.UUID, settings: Settings) -> AccessToken:
    now = datetime.now(UTC)
    lifetime = timedelta(minutes=settings.access_token_ttl_minutes)
    payload = {"sub": str(user_id), "iat": now, "exp": now + lifetime}
    token = jwt.encode(
        payload, settings.jwt_secret_key.get_secret_value(), algorithm=settings.jwt_algorithm
    )
    return AccessToken(token=token, expires_in=int(lifetime.total_seconds()))


def decode_access_token(token: str, settings: Settings) -> uuid.UUID:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
            options={"require": ["sub", "exp", "iat"]},
        )
        return uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, ValueError) as exc:
        raise InvalidTokenError from exc


def generate_refresh_token() -> str:
    return secrets.token_urlsafe(32)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
