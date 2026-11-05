import enum
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, str_enum

if TYPE_CHECKING:
    from app.models.auth import AuthIdentity, RefreshSession
    from app.models.cart import Cart


class UserRole(enum.StrEnum):
    USER = "user"
    ADMIN = "admin"


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    # Пустой хеш появится у аккаунтов, созданных только через Google или Apple.
    password_hash: Mapped[str | None] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(str_enum(UserRole), default=UserRole.USER)

    carts: Mapped[list["Cart"]] = relationship(
        back_populates="owner", cascade="all, delete-orphan", passive_deletes=True
    )
    refresh_sessions: Mapped[list["RefreshSession"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    identities: Mapped[list["AuthIdentity"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )

    @property
    def is_admin(self) -> bool:
        return self.role == UserRole.ADMIN
