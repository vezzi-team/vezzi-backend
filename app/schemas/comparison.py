from pydantic import Field

from app.planner.chain_totals import LineStatus
from app.schemas.catalog import ProductRead, StoreRead
from app.schemas.common import Schema, Timestamp


class ChainLineRead(Schema):
    product: ProductRead
    quantity: int
    status: LineStatus = Field(
        description=(
            "available: цена подтверждена и входит в суммы. Остальные значения означают пропуск: "
            "stale (цена устарела), out_of_stock (нет в наличии), "
            "stock_unknown (наличие неизвестно), not_sold (сеть не продаёт товар)"
        )
    )
    unit_price_kopecks: int | None = Field(
        description="Обычная цена упаковки. У пропусков это последняя известная цена"
    )
    total_kopecks: int | None = Field(
        description="Цена × количество. Есть только у строк со статусом available"
    )
    card_price_kopecks: int | None = Field(
        description="Цена по карте лояльности. Показывается отдельно и в суммы не входит (F06)"
    )
    price_type: str | None = Field(examples=["current", "promo"])
    price_conditions: str | None = Field(description="Условия акции")
    store: StoreRead | None = Field(description="Магазин сети, где наблюдалась эта цена")
    price_updated_at: Timestamp | None = Field(description="Когда источник видел эту цену")
    is_fresh: bool | None = Field(description="false: цена старше допустимого возраста")


class ChainTotalRead(Schema):
    chain: str = Field(examples=["Пятёрочка"])
    is_complete: bool = Field(description="В сети подтверждены все товары корзины")
    total_kopecks: int | None = Field(
        description="Итог по сети. null, если корзина неполная: сравнивать его с полной нельзя"
    )
    found_total_kopecks: int = Field(description="Сумма только по найденным товарам")
    items_count: int
    found_items_count: int
    coverage_percent: int = Field(
        description="Доля найденных позиций, округлена вниз: 100 только у полной корзины"
    )
    missing_products: list[ProductRead] = Field(description="Пропуски, причина в строке")
    oldest_price_updated_at: Timestamp | None = Field(
        description="Самая старая цена в суммах: насколько актуален итог"
    )
    lines: list[ChainLineRead] = Field(description="Строки в порядке корзины")


class ChainComparison(Schema):
    chains: list[ChainTotalRead] = Field(
        description="Сначала полные корзины от дешёвой к дорогой, потом неполные по числу пропусков"
    )
    calculated_at: Timestamp
    offer_max_age_hours: int
    data_is_synthetic: bool
