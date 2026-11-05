from typing import Literal

from pydantic import Field

from app.schemas.common import Schema, Timestamp


class ImportRowError(Schema):
    sheet: str
    row: int
    message: str


class ImportReportRead(Schema):
    status: Literal["published", "unchanged"]
    import_id: int
    stores_count: int
    products_count: int
    offers_count: int
    rejected_rows_count: int
    is_synthetic: bool
    timestamps_shifted: bool
    skipped_weighted_products: int = Field(
        description="Весовые товары пропущены: в MVP они не загружаются"
    )
    skipped_weighted_offers: int = Field(description="Цены пропущенных весовых товаров")
    fresh_offers_count: int = Field(
        description="Сколько цен участвует в расчёте прямо сейчас. Если мало, данные устарели"
    )
    errors: list[ImportRowError]


class CatalogImportRead(Schema):
    id: int
    status: str
    source_name: str
    is_synthetic: bool
    timestamps_shifted: bool
    stores_count: int
    products_count: int
    offers_count: int
    rejected_rows_count: int
    created_at: Timestamp
