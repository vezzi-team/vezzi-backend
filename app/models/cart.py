"""Корзина пользователя: какие товары и сколько он хочет купить (F01, F03).

Корзина не привязана к магазинам и ценам. Где и почём купить, решает расчёт плана.
"""

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, SmallInteger, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, str_enum
from app.models.catalog import Product

if TYPE_CHECKING:
    from app.models.user import User


class CartStatus(enum.StrEnum):
    ACTIVE = "active"
    SAVED = "saved"
    COMPLETED = "completed"


class Cart(TimestampMixin, Base):
    __tablename__ = "carts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    status: Mapped[CartStatus] = mapped_column(str_enum(CartStatus), default=CartStatus.ACTIVE)

    owner: Mapped["User"] = relationship(back_populates="carts")
    items: Mapped[list["CartItem"]] = relationship(
        back_populates="cart",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="CartItem.added_at",
    )


class CartItem(Base):
    """Позиция корзины. Составной ключ (корзина, товар) не даёт завести один товар дважды."""

    __tablename__ = "cart_items"
    __table_args__ = (CheckConstraint("quantity BETWEEN 1 AND 99", name="quantity_range"),)

    cart_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("carts.id", ondelete="CASCADE"), primary_key=True
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), primary_key=True
    )
    quantity: Mapped[int] = mapped_column(SmallInteger)
    added_at: Mapped[datetime] = mapped_column(server_default=func.now())

    cart: Mapped[Cart] = relationship(back_populates="items")
    product: Mapped[Product] = relationship(lazy="joined")
