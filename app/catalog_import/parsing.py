"""Разбор и проверка одной строки таблицы.

Excel отдаёт значения разных типов: число, строку «127,21», bool, datetime.
Функции ниже приводят их к строгим типам или бросают InvalidRowError с понятной причиной.
"""

import json
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

from app.catalog_import.records import OfferRecord, ProductRecord, StoreRecord
from app.models.catalog import PackageUnit, StoreFormat

type Row = Mapping[str, Any]


class InvalidRowError(Exception):
    pass


# Единица из таблицы -> (базовая единица, множитель). Храним в г, мл, шт или м.
UNITS: dict[str, tuple[PackageUnit, int]] = {
    "г": (PackageUnit.GRAM, 1),
    "гр": (PackageUnit.GRAM, 1),
    "g": (PackageUnit.GRAM, 1),
    "кг": (PackageUnit.GRAM, 1000),
    "kg": (PackageUnit.GRAM, 1000),
    "мл": (PackageUnit.MILLILITER, 1),
    "ml": (PackageUnit.MILLILITER, 1),
    "л": (PackageUnit.MILLILITER, 1000),
    "l": (PackageUnit.MILLILITER, 1000),
    "шт": (PackageUnit.PIECE, 1),
    "pcs": (PackageUnit.PIECE, 1),
    "м": (PackageUnit.METER, 1),
    "m": (PackageUnit.METER, 1),
}
# Фасовка хранится в колонке NUMERIC(10, 3): до тысячной доли и меньше десяти миллионов.
PACKAGE_PRECISION = Decimal("0.001")
MAX_PACKAGE_AMOUNT = Decimal(10_000_000)
# Так команда данных помечает пустые ячейки текстом.
_EMPTY_MARKERS = {"-", "—", "–"}
_URL_PREFIXES = ("https://", "http://")
_CARD_PRICE_TYPES = {"card", "loyalty", "карта", "по карте"}

_TRUE = {"true", "1", "да", "yes", "y", "есть"}
_FALSE = {"false", "0", "нет", "no", "n"}
_DATETIME_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M")


def parse_store(row: Row) -> StoreRecord:
    latitude = _number(row, "latitude")
    longitude = _number(row, "longitude")
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        raise InvalidRowError("координаты вне допустимого диапазона")
    store_format = _text(row, "store_format") or StoreFormat.SUPERMARKET.value
    if store_format not in StoreFormat:
        raise InvalidRowError(f"неизвестный store_format «{store_format}»")
    return StoreRecord(
        external_id=_external_id(row, "store_id"),
        chain=_required_text(row, "chain_name"),
        name=_required_text(row, "store_name"),
        address=_required_text(row, "address"),
        latitude=float(latitude),
        longitude=float(longitude),
        format=StoreFormat(store_format),
        is_active=_boolean(row, "is_active", default=True) is not False,
    )


def parse_product(row: Row) -> ProductRecord:
    unit_text = _required_text(row, "unit").lower().rstrip(".")
    if unit_text not in UNITS:
        raise InvalidRowError(f"неизвестная единица «{unit_text}»")
    unit, multiplier = UNITS[unit_text]
    amount = _number(row, "quantity") * multiplier
    if amount <= 0:
        raise InvalidRowError(f"фасовка {amount} {unit.value}: нужно положительное число")
    if amount >= MAX_PACKAGE_AMOUNT or amount != amount.quantize(PACKAGE_PRECISION):
        raise InvalidRowError(f"фасовка {amount} {unit.value}: слишком большая или слишком точная")
    return ProductRecord(
        external_id=_external_id(row, "product_id"),
        name=_required_text(row, "product_name"),
        brand=_text(row, "brand"),
        category=_required_text(row, "category"),
        product_type=_text(row, "product_type"),
        package_amount=amount,
        package_unit=unit,
        attributes=_json_object(row, "attributes_json"),
    )


def parse_offer(row: Row, row_number: int, timezone: ZoneInfo) -> OfferRecord:
    match_status = _text(row, "match_status")
    if match_status is not None and match_status != "matched":
        raise InvalidRowError(f"товар не сопоставлен (match_status={match_status})")
    currency = _text(row, "currency")
    if currency is not None and currency.upper() != "RUB":
        raise InvalidRowError(f"валюта {currency} не поддерживается")
    price_type = _text(row, "price_type", max_length=20)
    if price_type is not None and price_type.lower() in _CARD_PRICE_TYPES:
        raise InvalidRowError("цену по карте указывайте в колонке card_price")
    return OfferRecord(
        row=row_number,
        store_external_id=_external_id(row, "store_id"),
        product_external_id=_external_id(row, "product_id"),
        price_kopecks=_price_kopecks(row, "price"),
        card_price_kopecks=_optional_price_kopecks(row, "card_price"),
        in_stock=_boolean(row, "in_stock", default=None),
        source_updated_at=_datetime(row, "updated_at", timezone),
        price_type=price_type,
        price_conditions=_text(row, "price_conditions", max_length=300),
        source_product_id=_text(row, "source_product_id", max_length=100),
        source_url=_url(row, "source_url"),
    )


def is_sold_by_weight(row: Row) -> bool:
    """Весовой товар: цена указана за 1 кг, а сколько он будет весить на кассе, неизвестно.

    В MVP такие товары не загружаются: расчёт должен сходиться до копейки (ТЗ, F06).
    """
    attributes = _json_object(row, "attributes_json")
    return str(attributes.get("sold_by", "")).strip().lower() == "весовой"


def product_external_id(row: Row) -> str:
    return _external_id(row, "product_id")


def is_synthetic_row(row: Row) -> bool:
    return _text(row, "data_origin") == "synthetic"


def _clean(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, float):
        # repr(0.93) == "0.93" без хвоста двоичной погрешности, а 1.0 из Excel означает id 1.
        value = int(value) if value.is_integer() else repr(value)
    text = str(value).strip()
    if not text or text in _EMPTY_MARKERS:
        return None
    return text


def _text(row: Row, column: str, max_length: int | None = None) -> str | None:
    text = _clean(row.get(column))
    if text is not None and max_length is not None and len(text) > max_length:
        raise InvalidRowError(f"в колонке {column} больше {max_length} символов")
    return text


def _required_text(row: Row, column: str) -> str:
    text = _text(row, column)
    if text is None:
        raise InvalidRowError(f"не заполнена колонка {column}")
    return text


def _external_id(row: Row, column: str) -> str:
    return _required_text(row, column)


def _number(row: Row, column: str) -> Decimal:
    if isinstance(row.get(column), bool):
        raise InvalidRowError(f"в колонке {column} ожидается число")
    text = _required_text(row, column).replace(",", ".").replace(" ", "")
    try:
        number = Decimal(text)
    except InvalidOperation as exc:
        raise InvalidRowError(f"в колонке {column} ожидается число, а не «{text}»") from exc
    if not number.is_finite():
        raise InvalidRowError(f"в колонке {column} ожидается число")
    return number


def _price_kopecks(row: Row, column: str) -> int:
    kopecks = _number(row, column) * 100
    if kopecks != kopecks.to_integral_value():
        raise InvalidRowError("цена должна быть указана с точностью до копеек")
    if kopecks <= 0:
        raise InvalidRowError("цена должна быть больше нуля")
    return int(kopecks)


def _optional_price_kopecks(row: Row, column: str) -> int | None:
    return None if _text(row, column) is None else _price_kopecks(row, column)


def _boolean(row: Row, column: str, default: bool | None) -> bool | None:
    value = row.get(column)
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in _TRUE:
        return True
    if text in _FALSE:
        return False
    raise InvalidRowError(f"в колонке {column} ожидается да/нет, а не «{value}»")


def _datetime(row: Row, column: str, timezone: ZoneInfo) -> datetime:
    value = row.get(column)
    if isinstance(value, datetime):
        parsed = value
    else:
        text = _required_text(row, column)
        parsed = _parse_datetime_text(text, column)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone)
    return parsed


def _parse_datetime_text(text: str, column: str) -> datetime:
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        pass
    for pattern in _DATETIME_FORMATS:
        try:
            return datetime.strptime(text, pattern)  # noqa: DTZ007 (пояс добавляется ниже)
        except ValueError:
            continue
    raise InvalidRowError(f"в колонке {column} непонятная дата «{text}»")


def _url(row: Row, column: str) -> str | None:
    url = _text(row, column, max_length=500)
    if url is not None and not url.lower().startswith(_URL_PREFIXES):
        raise InvalidRowError(f"в колонке {column} ожидается ссылка http:// или https://")
    return url


def _json_object(row: Row, column: str) -> dict[str, Any]:
    text = _text(row, column)
    if text is None:
        return {}
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise InvalidRowError(f"в колонке {column} некорректный JSON") from exc
    if not isinstance(value, dict):
        raise InvalidRowError(f"в колонке {column} ожидается JSON-объект")
    return value
