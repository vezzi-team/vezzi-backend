"""Проверенные строки каталога, готовые к записи в базу."""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from app.models.catalog import PackageUnit, StoreFormat


@dataclass(frozen=True)
class StoreRecord:
    external_id: str
    chain: str
    name: str
    address: str
    latitude: float
    longitude: float
    format: StoreFormat
    is_active: bool


@dataclass(frozen=True)
class ProductRecord:
    external_id: str
    name: str
    brand: str | None
    category: str
    product_type: str | None
    package_amount: Decimal
    package_unit: PackageUnit
    attributes: dict[str, Any]


@dataclass(frozen=True)
class OfferRecord:
    row: int
    store_external_id: str
    product_external_id: str
    price_kopecks: int
    card_price_kopecks: int | None
    in_stock: bool | None
    source_updated_at: datetime
    price_type: str | None
    price_conditions: str | None
    source_product_id: str | None
    source_url: str | None


@dataclass(frozen=True)
class RowError:
    sheet: str
    row: int
    message: str


@dataclass
class ParsedCatalog:
    stores: list[StoreRecord] = field(default_factory=list)
    products: list[ProductRecord] = field(default_factory=list)
    offers: list[OfferRecord] = field(default_factory=list)
    errors: list[RowError] = field(default_factory=list)
    is_synthetic: bool = False
    # Весовые товары и их цены пропускаются намеренно, это не ошибка в данных.
    skipped_weighted_products: int = 0
    skipped_weighted_offers: int = 0
