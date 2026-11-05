"""Каталог: магазины, товары, загрузки каталога и предложения (цены).

Магазины и товары обновляются по внешнему идентификатору из таблицы команды.
Предложения привязаны к конкретной загрузке (снимку). Активен ровно один снимок:
новая загрузка публикуется одной транзакцией, поэтому пользователи никогда
не видят наполовину загруженный каталог (требования D02 и N04).
"""

import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, str_enum


class StoreFormat(enum.StrEnum):
    CONVENIENCE = "convenience"
    SUPERMARKET = "supermarket"
    HYPERMARKET = "hypermarket"


class PackageUnit(enum.StrEnum):
    GRAM = "g"
    MILLILITER = "ml"
    PIECE = "pcs"
    METER = "m"


class Store(TimestampMixin, Base):
    __tablename__ = "stores"

    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[str] = mapped_column(String(64), unique=True)
    chain: Mapped[str] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(200))
    address: Mapped[str] = mapped_column(String(300))
    latitude: Mapped[float]
    longitude: Mapped[float]
    format: Mapped[StoreFormat] = mapped_column(
        str_enum(StoreFormat), default=StoreFormat.SUPERMARKET
    )
    is_active: Mapped[bool] = mapped_column(default=True)


class Product(TimestampMixin, Base):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("package_amount > 0", name="package_amount_positive"),
        Index(
            "ix_products_name_trgm",
            "name",
            postgresql_using="gin",
            postgresql_ops={"name": "gin_trgm_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(300))
    brand: Mapped[str | None] = mapped_column(String(100))
    category: Mapped[str] = mapped_column(String(100))
    product_type: Mapped[str | None] = mapped_column(String(100))
    # Фасовка в базовых единицах: граммы, миллилитры, штуки или метры (0,9 л -> 900 мл).
    # Numeric, а не int: бывают упаковки по 41,5 г.
    package_amount: Mapped[Decimal] = mapped_column(Numeric(10, 3))
    package_unit: Mapped[PackageUnit] = mapped_column(str_enum(PackageUnit))
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class ImportStatus(enum.StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class CatalogImport(Base):
    __tablename__ = "catalog_imports"
    __table_args__ = (
        Index(
            "uq_catalog_imports_single_active",
            "status",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[ImportStatus] = mapped_column(str_enum(ImportStatus))
    source_name: Mapped[str] = mapped_column(String(255))
    file_sha256: Mapped[str] = mapped_column(String(64), index=True)
    is_synthetic: Mapped[bool]
    timestamps_shifted: Mapped[bool] = mapped_column(default=False)
    stores_count: Mapped[int]
    products_count: Mapped[int]
    offers_count: Mapped[int]
    rejected_rows_count: Mapped[int]
    imported_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Offer(Base):
    __tablename__ = "offers"
    __table_args__ = (
        UniqueConstraint("import_id", "store_id", "product_id"),
        CheckConstraint("price_kopecks > 0", name="price_positive"),
        CheckConstraint("card_price_kopecks > 0", name="card_price_positive"),
        Index("ix_offers_import_product", "import_id", "product_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    import_id: Mapped[int] = mapped_column(ForeignKey("catalog_imports.id", ondelete="CASCADE"))
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"))
    # Цена без условий, она идёт в расчёт. Цена по карте хранится отдельно и в итог не входит (F06).
    price_kopecks: Mapped[int]
    card_price_kopecks: Mapped[int | None]
    # None означает, что наличие неизвестно. Такое предложение не считается доступным (F04).
    in_stock: Mapped[bool | None]
    price_type: Mapped[str | None] = mapped_column(String(20))
    price_conditions: Mapped[str | None] = mapped_column(String(300))
    source_product_id: Mapped[str | None] = mapped_column(String(100))
    source_url: Mapped[str | None] = mapped_column(String(500))
    # Когда цену обновил источник. Повторная загрузка старой цены её не «освежает».
    source_updated_at: Mapped[datetime]

    store: Mapped[Store] = relationship()
    product: Mapped[Product] = relationship()

    @property
    def stable_id(self) -> str:
        """Номер строки меняется с каждой загрузкой, а пара «магазин, товар» остаётся той же."""
        return f"{self.store_id}-{self.product_id}"
