"""Формат Excel-файла каталога. Единственное место, где описаны листы и колонки.

По этому описанию проверяется загружаемый файл и генерируется шаблон для команды
(`vezzi catalog-template`). Лишние листы и колонки при загрузке игнорируются.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Column:
    name: str
    required: bool
    description: str
    example: object


STORES_SHEET = "stores"
PRODUCTS_SHEET = "products"
OFFERS_SHEET = "offers"

SHEETS: dict[str, tuple[Column, ...]] = {
    STORES_SHEET: (
        Column("store_id", True, "Постоянный идентификатор магазина в таблице", 1),
        Column("chain_name", True, "Сеть", "Пятёрочка"),
        Column("store_name", True, "Название точки", "Пятёрочка, Малый пр. В.О., 52"),
        Column("address", True, "Адрес", "Санкт-Петербург, Малый пр. В.О., 52"),
        Column("latitude", True, "Широта (WGS84), например 59.9417", 59.9417),
        Column("longitude", True, "Долгота (WGS84), например 30.2654", 30.2654),
        Column("store_format", False, "convenience / supermarket / hypermarket", "supermarket"),
        Column("is_active", False, "Работает ли магазин (по умолчанию да)", True),
    ),
    PRODUCTS_SHEET: (
        Column("product_id", True, "Постоянный идентификатор канонического товара", 1),
        Column(
            "product_name", True, "Полное название с фасовкой", "Простоквашино Молоко 2,5%, 930 мл"
        ),
        Column("brand", False, "Бренд", "Простоквашино"),
        Column("category", True, "Категория", "Молочные продукты"),
        Column("product_type", False, "Вид товара", "Молоко"),
        Column("quantity", True, "Количество в упаковке, число (можно дробное: 41,5)", 0.93),
        Column("unit", True, "Единица: г, кг, мл, л, шт или м", "л"),
        Column(
            "attributes_json",
            False,
            "Характеристики в JSON-объекте. Товары с sold_by = «весовой» в MVP не загружаются",
            '{"fat_percent": 2.5, "sold_by": "штучный"}',
        ),
    ),
    OFFERS_SHEET: (
        Column("product_id", True, "product_id с листа products", 1),
        Column("store_id", True, "store_id с листа stores", 1),
        Column("price", True, "Обычная цена за упаковку в рублях, до копеек", 89.99),
        Column(
            "card_price",
            False,
            "Цена по карте лояльности. В итог не входит, показывается рядом",
            79.99,
        ),
        Column("in_stock", False, "Есть в наличии: да/нет, пусто: неизвестно", True),
        Column(
            "updated_at",
            True,
            "Когда источник обновил цену (по Москве, если без пояса)",
            "2026-10-30 09:00:00",
        ),
        Column("match_status", False, "Загружаются только строки со статусом matched", "matched"),
        Column("price_type", False, "regular / promo / current", "regular"),
        Column(
            "price_conditions", False, "Условия акции, до 300 символов", "до 10.11, 2 по цене 1"
        ),
        Column("source_product_id", False, "Идентификатор товара у источника", "1-00001"),
        Column(
            "source_url",
            False,
            "Страница товара у источника, http:// или https://",
            "https://example.com/products/1-00001",
        ),
        Column("currency", False, "Только RUB", "RUB"),
        Column(
            "data_origin", False, "synthetic помечает весь каталог как демонстрационный", "real"
        ),
    ),
}


def required_columns(sheet: str) -> set[str]:
    return {column.name for column in SHEETS[sheet] if column.required}
