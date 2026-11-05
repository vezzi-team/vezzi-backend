import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, str_enum

if TYPE_CHECKING:
    from app.models.user import User


class RefreshSession(Base):
    """Сессия одного устройства.

    При каждом обновлении токена старая запись отзывается и создаётся новая
    с тем же family_id. Если кто-то предъявит уже отозванный токен, значит токен
    украли или скопировали: отзываем всю семью, и устройству придётся войти заново.
    """

    __tablename__ = "refresh_sessions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    family_id: Mapped[uuid.UUID] = mapped_column(index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    expires_at: Mapped[datetime]
    revoked_at: Mapped[datetime | None]

    user: Mapped["User"] = relationship(back_populates="refresh_sessions")


class AuthProvider(enum.StrEnum):
    GOOGLE = "google"
    APPLE = "apple"


class AuthIdentity(Base):
    """Привязка аккаунта к внешнему провайдеру входа (Google, Apple).

    Таблица заготовлена под следующий этап. Пользователя ищем по паре
    (provider, subject), где subject содержит неизменяемый `sub` из проверенного
    identity token. Email для этого не годится: его можно сменить или скрыть.
    """

    __tablename__ = "auth_identities"
    __table_args__ = (UniqueConstraint("provider", "subject"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[AuthProvider] = mapped_column(str_enum(AuthProvider))
    subject: Mapped[str] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(320))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="identities")
