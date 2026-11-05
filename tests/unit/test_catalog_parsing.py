from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from app.catalog_import.parsing import (
    InvalidRowError,
    is_sold_by_weight,
    parse_offer,
    parse_product,
    parse_store,
)
from app.models.catalog import PackageUnit, StoreFormat

MOSCOW = ZoneInfo("Europe/Moscow")

PRODUCT = {
    "product_id": 1,
    "product_name": "Молоко 2,5%, 930 мл",
    "category": "Молочные продукты",
    "quantity": 0.93,
    "unit": "л",
}
OFFER = {"product_id": 1, "store_id": 2, "price": 89.99, "updated_at": "2026-10-30 09:00:00"}
STORE = {
    "store_id": 7,
    "chain_name": "Сеть",
    "store_name": "Точка",
    "address": "Адрес",
    "latitude": 59.94,
    "longitude": 30.26,
}


class TestProduct:
    @pytest.mark.parametrize(
        ("quantity", "unit", "amount", "base_unit"),
        [
            (0.93, "л", 930, PackageUnit.MILLILITER),
            ("0,5", "кг", 500, PackageUnit.GRAM),
            (0.112, "кг", 112, PackageUnit.GRAM),
            (450, "г", 450, PackageUnit.GRAM),
            (10, "шт", 10, PackageUnit.PIECE),
            (1, "L", 1000, PackageUnit.MILLILITER),
            (41.5, "г", Decimal("41.5"), PackageUnit.GRAM),
            (0.0005, "кг", Decimal("0.5"), PackageUnit.GRAM),
            (50, "м", 50, PackageUnit.METER),
        ],
    )
    def test_units_are_normalized(
        self, quantity: object, unit: str, amount: Decimal | int, base_unit: PackageUnit
    ) -> None:
        product = parse_product({**PRODUCT, "quantity": quantity, "unit": unit})
        assert (product.package_amount, product.package_unit) == (amount, base_unit)

    def test_float_id_from_excel_becomes_clean_string(self) -> None:
        assert parse_product({**PRODUCT, "product_id": 15.0}).external_id == "15"

    @pytest.mark.parametrize("brand", ["—", "-", "  ", None])
    def test_dash_means_empty(self, brand: object) -> None:
        assert parse_product({**PRODUCT, "brand": brand}).brand is None

    @pytest.mark.parametrize(
        ("attributes", "expected"),
        [
            ('{"sold_by": "весовой"}', True),
            ('{"sold_by": " Весовой "}', True),
            ('{"sold_by": "штучный"}', False),
            (None, False),
        ],
    )
    def test_sold_by_weight_comes_from_attributes(
        self, attributes: str | None, expected: bool
    ) -> None:
        assert is_sold_by_weight({**PRODUCT, "attributes_json": attributes}) is expected

    @pytest.mark.parametrize(
        ("changes", "message"),
        [
            ({"unit": "ящик"}, "неизвестная единица"),
            ({"quantity": 0, "unit": "кг"}, "положительное число"),
            ({"quantity": 0.0000001, "unit": "кг"}, "слишком точная"),
            ({"quantity": 1e9, "unit": "кг"}, "слишком большая"),
            ({"quantity": "много"}, "ожидается число"),
            ({"product_name": "  "}, "не заполнена колонка product_name"),
            ({"attributes_json": "[1, 2]"}, "JSON-объект"),
        ],
    )
    def test_invalid_rows_are_rejected_with_reason(self, changes: dict, message: str) -> None:
        with pytest.raises(InvalidRowError, match=message):
            parse_product({**PRODUCT, **changes})


class TestOffer:
    def test_price_is_converted_to_kopecks_without_float_errors(self) -> None:
        assert (
            parse_offer({**OFFER, "price": 0.1 + 0.2 - 0.3 + 19.99}, 2, MOSCOW).price_kopecks
            == 1999
        )
        assert parse_offer({**OFFER, "price": "127,21"}, 2, MOSCOW).price_kopecks == 12721
        assert parse_offer({**OFFER, "price": 123}, 2, MOSCOW).price_kopecks == 12300

    @pytest.mark.parametrize("price", [None, 0, -5, 10.005, "abc"])
    def test_bad_prices(self, price: object) -> None:
        with pytest.raises(InvalidRowError):
            parse_offer({**OFFER, "price": price}, 2, MOSCOW)

    def test_naive_time_is_moscow_time(self) -> None:
        offer = parse_offer(OFFER, 2, MOSCOW)
        assert offer.source_updated_at == datetime(2026, 10, 30, 6, 0, tzinfo=UTC)

    def test_time_with_offset_is_kept(self) -> None:
        offer = parse_offer({**OFFER, "updated_at": "2026-10-30T09:00:00+00:00"}, 2, MOSCOW)
        assert offer.source_updated_at == datetime(2026, 10, 30, 9, 0, tzinfo=UTC)

    def test_excel_datetime_cell(self) -> None:
        excel_cell = datetime(2026, 10, 30, 9, 0)  # noqa: DTZ001 (Excel отдаёт время без пояса)
        offer = parse_offer({**OFFER, "updated_at": excel_cell}, 2, MOSCOW)
        assert offer.source_updated_at.utcoffset() is not None

    @pytest.mark.parametrize(
        ("value", "expected"), [(True, True), ("нет", False), ("1", True), (None, None), ("", None)]
    )
    def test_availability(self, value: object, expected: bool | None) -> None:
        assert parse_offer({**OFFER, "in_stock": value}, 2, MOSCOW).in_stock is expected

    @pytest.mark.parametrize("status", ["needs_review", "unmatched"])
    def test_only_matched_offers_are_loaded(self, status: str) -> None:
        with pytest.raises(InvalidRowError, match="не сопоставлен"):
            parse_offer({**OFFER, "match_status": status}, 2, MOSCOW)

    def test_source_url(self) -> None:
        url = "https://spb.vkusvill.ru/goods/vv100001"
        assert parse_offer({**OFFER, "source_url": url}, 2, MOSCOW).source_url == url
        with pytest.raises(InvalidRowError, match="ссылка"):
            parse_offer({**OFFER, "source_url": "javascript:alert(1)"}, 2, MOSCOW)

    def test_card_price_and_conditions_are_kept_apart_from_the_price(self) -> None:
        row = {
            **OFFER,
            "card_price": "79,99",
            "price_conditions": "до 10.11",
            "price_type": "promo",
        }
        offer = parse_offer(row, 2, MOSCOW)
        assert (offer.price_kopecks, offer.card_price_kopecks) == (8999, 7999)
        assert (offer.price_type, offer.price_conditions) == ("promo", "до 10.11")

    def test_card_price_is_optional(self) -> None:
        assert parse_offer(OFFER, 2, MOSCOW).card_price_kopecks is None

    def test_card_price_in_main_column_is_rejected(self) -> None:
        with pytest.raises(InvalidRowError, match="card_price"):
            parse_offer({**OFFER, "price_type": "card"}, 2, MOSCOW)

    @pytest.mark.parametrize(
        ("column", "value"),
        [("card_price", 0), ("card_price", 10.005), ("price_conditions", "я" * 301)],
    )
    def test_bad_optional_values(self, column: str, value: object) -> None:
        with pytest.raises(InvalidRowError):
            parse_offer({**OFFER, column: value}, 2, MOSCOW)

    def test_foreign_currency_is_rejected(self) -> None:
        with pytest.raises(InvalidRowError, match="валюта"):
            parse_offer({**OFFER, "currency": "USD"}, 2, MOSCOW)


class TestStore:
    def test_defaults(self) -> None:
        store = parse_store(STORE)
        assert store.external_id == "7"
        assert store.format is StoreFormat.SUPERMARKET
        assert store.is_active is True

    def test_coordinates_out_of_range(self) -> None:
        with pytest.raises(InvalidRowError, match="координаты"):
            parse_store({**STORE, "latitude": 159.9})

    def test_unknown_format(self) -> None:
        with pytest.raises(InvalidRowError, match="store_format"):
            parse_store({**STORE, "store_format": "mall"})
