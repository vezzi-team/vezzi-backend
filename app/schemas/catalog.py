from typing import Literal

from pydantic import Field

from app.models.catalog import PackageUnit, StoreFormat
from app.schemas.common import Schema, Timestamp


class ProductRead(Schema):
    id: int
    name: str = Field(examples=["Простоквашино Молоко 2,5%, 930 мл"])
    brand: str | None
    category: str
    product_type: str | None
    package_amount: float = Field(description="Фасовка в базовых единицах", examples=[930])
    package_unit: PackageUnit = Field(description="g: граммы, ml: миллилитры, pcs: штуки, m: метры")


class StoreRead(Schema):
    id: int
    chain: str
    name: str
    address: str
    latitude: float
    longitude: float
    format: StoreFormat


class StoreWithDistance(StoreRead):
    distance_meters: int | None = Field(
        default=None, description="Расстояние по прямой до переданной точки"
    )


class OfferRead(Schema):
    store: StoreRead
    price_kopecks: int = Field(examples=[8999], description="Обычная цена, она идёт в расчёт")
    card_price_kopecks: int | None = Field(
        description="Цена по карте лояльности. В итоги не входит (F06)"
    )
    in_stock: bool | None = Field(description="null: наличие неизвестно")
    price_type: str | None = Field(examples=["current", "promo"])
    price_conditions: str | None = Field(description="Условия акции")
    source_url: str | None = Field(description="Страница товара у источника цены")
    source_updated_at: Timestamp
    is_fresh: bool = Field(description="Цена не старше допустимого возраста и участвует в расчёте")


class ProductDetail(ProductRead):
    attributes: dict[str, object]
    offers: list[OfferRead]


class CatalogStatus(Schema):
    is_loaded: bool
    import_id: int | None = None
    imported_at: Timestamp | None = None
    is_synthetic: bool = Field(
        default=False, description="Данные демонстрационные: приложение должно это показать"
    )
    stores_count: int = 0
    products_count: int = 0
    offers_count: int = 0
    fresh_offers_count: int = Field(
        default=0, description="Сколько цен сейчас свежие и в наличии, то есть участвуют в расчёте"
    )
    offer_max_age_hours: int


class ExportedOffer(Schema):
    id: str = Field(
        validation_alias="stable_id",
        examples=["7-42"],
        description="Постоянный номер: магазин-товар. Новая загрузка обновляет ту же запись",
    )
    product_id: int
    store_id: int
    price_kopecks: int
    currency: Literal["RUB"] = "RUB"
    card_price_kopecks: int | None
    in_stock: bool | None
    price_type: str | None
    price_conditions: str | None
    source_product_id: str | None
    source_url: str | None
    source_updated_at: Timestamp


class CatalogExport(Schema):
    """Весь активный каталог для локального кэша iOS-приложения."""

    import_id: int
    imported_at: Timestamp
    is_synthetic: bool
    offer_max_age_hours: int = Field(
        description="Цена старше этого возраста в расчёт не идёт. Клиент сравнивает сам"
    )
    products: list[ProductRead]
    stores: list[StoreRead]
    offers: list[ExportedOffer] = Field(
        description="Все цены снимка, в том числе устаревшие и без наличия"
    )
