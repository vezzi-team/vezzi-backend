import uuid

from pydantic import EmailStr, Field

from app.models.user import UserRole
from app.schemas.common import Schema, Timestamp

PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 128


class Credentials(Schema):
    email: EmailStr = Field(examples=["student@itmo.ru"])
    password: str = Field(
        min_length=PASSWORD_MIN_LENGTH,
        max_length=PASSWORD_MAX_LENGTH,
        examples=["correct-horse-42"],
    )


class LoginRequest(Schema):
    email: EmailStr = Field(examples=["student@itmo.ru"])
    password: str = Field(
        min_length=1, max_length=PASSWORD_MAX_LENGTH, examples=["correct-horse-42"]
    )


class RefreshRequest(Schema):
    refresh_token: str = Field(min_length=1, max_length=512)


class ChangePasswordRequest(Schema):
    current_password: str = Field(min_length=1, max_length=PASSWORD_MAX_LENGTH)
    new_password: str = Field(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)


class TokenPair(Schema):
    access_token: str = Field(description="JWT для заголовка Authorization: Bearer <token>")
    refresh_token: str = Field(description="Одноразовый токен для POST /auth/refresh")
    token_type: str = "bearer"  # noqa: S105 (тип токена, а не секрет)
    expires_in: int = Field(
        description="Через сколько секунд истечёт access_token", examples=[1800]
    )


class UserRead(Schema):
    id: uuid.UUID
    email: EmailStr
    role: UserRole
    created_at: Timestamp


class AuthResponse(Schema):
    user: UserRead
    tokens: TokenPair
