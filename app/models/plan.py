"""Сохранённые планы покупки (D01): план → остановки в магазинах → позиции.

Цены и время копируются в план в момент расчёта. Поэтому план не меняется,
когда загружается новый каталог, и его можно открыть в истории через месяц.
"""

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import BigInteger, ForeignKey, Index, SmallInteger, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, str_enum
from app.models.catalog import Product, Store

if TYPE_CHECKING:
    from app.models.cart import Cart


class PlanStatus(enum.StrEnum):
    PLANNED = "planned"
    """Рассчитан и показан пользователю, но ещё не выбран."""
    ACTIVE = "active"
    """Пользователь выбрал план и идёт по магазинам."""
    COMPLETED = "completed"


class PlanItemStatus(enum.StrEnum):
    PLANNED = "planned"
    BOUGHT = "bought"
    MISSING = "missing"
    """Товара не оказалось в магазине."""


class Plan(TimestampMixin, Base):
    __tablename__ = "plans"
    __table_args__ = (
        # У корзины не может быть двух планов, по которым пользователь идёт одновременно.
        Index(
            "uq_plans_single_active_per_cart",
            "cart_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # После удаления корзины план остаётся в истории.
    cart_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("carts.id", ondelete="SET NULL"), index=True
    )
    status: Mapped[PlanStatus] = mapped_column(str_enum(PlanStatus), default=PlanStatus.PLANNED)
    rank: Mapped[int] = mapped_column(SmallInteger)
    total_kopecks: Mapped[int]
    savings_kopecks: Mapped[int | None]
    walking_seconds: Mapped[int]
    walking_meters: Mapped[int]
    shopping_seconds: Mapped[int]
    route_provider: Mapped[str] = mapped_column(String(20))
    route_uses_road_network: Mapped[bool]
    # Точки линии маршрута: [{"latitude": ..., "longitude": ...}, ...].
    route_points: Mapped[list[dict[str, float]]] = mapped_column(JSONB)
    data_is_synthetic: Mapped[bool]
    started_at: Mapped[datetime | None]
    completed_at: Mapped[datetime | None]

    cart: Mapped["Cart | None"] = relationship()
    stops: Mapped[list["PlanStop"]] = relationship(
        back_populates="plan",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="PlanStop.position",
    )

    @property
    def total_seconds(self) -> int:
        return self.walking_seconds + self.shopping_seconds

    @property
    def stores_count(self) -> int:
        return len(self.stops)

    @property
    def items(self) -> list["PlanItem"]:
        return [item for stop in self.stops for item in stop.items]

    @property
    def route(self) -> dict[str, Any]:
        return {
            "provider": self.route_provider,
            "uses_road_network": self.route_uses_road_network,
            "points": self.route_points,
        }


class PlanStop(Base):
    """Один магазин маршрута и путь до него от старта или предыдущего магазина."""

    __tablename__ = "plan_stops"
    __table_args__ = (UniqueConstraint("plan_id", "position"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("plans.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(SmallInteger)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id", ondelete="RESTRICT"))
    subtotal_kopecks: Mapped[int]
    shopping_seconds: Mapped[int]
    walk_from_previous_seconds: Mapped[int]
    walk_from_previous_meters: Mapped[int]

    plan: Mapped[Plan] = relationship(back_populates="stops")
    store: Mapped[Store] = relationship(lazy="joined")
    items: Mapped[list["PlanItem"]] = relationship(
        back_populates="stop",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="PlanItem.id",
    )


class PlanItem(Base):
    __tablename__ = "plan_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    stop_id: Mapped[int] = mapped_column(ForeignKey("plan_stops.id", ondelete="CASCADE"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"))
    quantity: Mapped[int] = mapped_column(SmallInteger)
    unit_price_kopecks: Mapped[int]
    card_price_kopecks: Mapped[int | None]
    price_type: Mapped[str | None] = mapped_column(String(20))
    price_conditions: Mapped[str | None] = mapped_column(String(300))
    price_updated_at: Mapped[datetime]
    status: Mapped[PlanItemStatus] = mapped_column(
        str_enum(PlanItemStatus), default=PlanItemStatus.PLANNED
    )
    # Запасной вариант: другой магазин этого же маршрута, где товар тоже продаётся.
    alternative_store_id: Mapped[int | None] = mapped_column(
        ForeignKey("stores.id", ondelete="SET NULL")
    )
    alternative_price_kopecks: Mapped[int | None]

    stop: Mapped[PlanStop] = relationship(back_populates="items")
    product: Mapped[Product] = relationship(lazy="joined")

    @property
    def total_kopecks(self) -> int:
        return self.unit_price_kopecks * self.quantity
