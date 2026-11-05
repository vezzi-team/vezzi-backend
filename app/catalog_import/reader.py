"""Чтение Excel-файла каталога и проверка всех строк."""

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import IO, Any, Protocol
from zipfile import BadZipFile
from zoneinfo import ZoneInfo

from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException

from app.catalog_import.columns import (
    OFFERS_SHEET,
    PRODUCTS_SHEET,
    SHEETS,
    STORES_SHEET,
    required_columns,
)
from app.catalog_import.parsing import (
    InvalidRowError,
    Row,
    is_sold_by_weight,
    is_synthetic_row,
    parse_offer,
    parse_product,
    parse_store,
    product_external_id,
)
from app.catalog_import.records import ParsedCatalog, RowError


class _Identified(Protocol):
    @property
    def external_id(self) -> str: ...


class CatalogFormatError(Exception):
    """Файл нельзя загрузить целиком: нет нужного листа, колонки или ни одной годной строки."""


def read_catalog(source: Path | IO[bytes], timezone: ZoneInfo) -> ParsedCatalog:
    try:
        workbook = load_workbook(source, read_only=True, data_only=True)
    except (BadZipFile, InvalidFileException, KeyError, OSError, ValueError) as exc:
        raise CatalogFormatError("Не удалось открыть файл. Нужен Excel в формате .xlsx") from exc

    try:
        sheets = {name: list(_rows(workbook, name)) for name in SHEETS}
    finally:
        workbook.close()

    catalog = ParsedCatalog()
    catalog.stores = _parse_unique(sheets[STORES_SHEET], STORES_SHEET, parse_store, catalog.errors)
    product_rows, weighted_ids = _without_weighted(sheets[PRODUCTS_SHEET])
    catalog.skipped_weighted_products = len(weighted_ids)
    catalog.products = _parse_unique(product_rows, PRODUCTS_SHEET, parse_product, catalog.errors)
    store_ids = {store.external_id for store in catalog.stores}
    product_ids = {product.external_id for product in catalog.products}

    seen_pairs: set[tuple[str, str]] = set()
    for number, row in sheets[OFFERS_SHEET]:
        catalog.is_synthetic = catalog.is_synthetic or is_synthetic_row(row)
        try:
            offer = parse_offer(row, number, timezone)
        except InvalidRowError as exc:
            catalog.errors.append(RowError(OFFERS_SHEET, number, str(exc)))
            continue
        if offer.product_external_id in weighted_ids:
            catalog.skipped_weighted_offers += 1
            continue
        pair = (offer.store_external_id, offer.product_external_id)
        if offer.store_external_id not in store_ids:
            reason = f"магазин {offer.store_external_id} не найден на листе stores"
        elif offer.product_external_id not in product_ids:
            reason = f"товар {offer.product_external_id} не найден на листе products"
        elif pair in seen_pairs:
            reason = "повтор: у этого магазина уже есть цена на этот товар"
        else:
            seen_pairs.add(pair)
            catalog.offers.append(offer)
            continue
        catalog.errors.append(RowError(OFFERS_SHEET, number, reason))

    return catalog


def _rows(workbook: Any, sheet: str) -> Iterator[tuple[int, Row]]:
    if sheet not in workbook.sheetnames:
        raise CatalogFormatError(f"В файле нет листа «{sheet}»")
    rows = workbook[sheet].iter_rows(values_only=True)
    header_row = next(rows, None)
    if header_row is None:
        raise CatalogFormatError(f"Лист «{sheet}» пустой")
    header = [str(cell).strip().lower() if cell is not None else "" for cell in header_row]
    missing = required_columns(sheet) - set(header)
    if missing:
        raise CatalogFormatError(f"На листе «{sheet}» нет колонок: {', '.join(sorted(missing))}")
    for number, values in enumerate(rows, start=2):
        if any(value is not None and value != "" for value in values):
            yield number, dict(zip(header, values, strict=False))


def _without_weighted(rows: list[tuple[int, Row]]) -> tuple[list[tuple[int, Row]], set[str]]:
    """Убирает весовые товары: в MVP они не загружаются (docs/decisions.md, решение 10)."""
    kept: list[tuple[int, Row]] = []
    weighted: set[str] = set()
    for number, row in rows:
        external_id = _weighted_product_id(row)
        if external_id is None:
            kept.append((number, row))
        else:
            weighted.add(external_id)
    return kept, weighted


def _weighted_product_id(row: Row) -> str | None:
    try:
        return product_external_id(row) if is_sold_by_weight(row) else None
    except InvalidRowError:
        return None  # строку с ошибкой разберёт parse_product и назовёт причину


def _parse_unique[T: _Identified](
    rows: list[tuple[int, Row]],
    sheet: str,
    parse: Callable[[Row], T],
    errors: list[RowError],
) -> list[T]:
    records: list[T] = []
    seen: set[str] = set()
    for number, row in rows:
        try:
            record = parse(row)
        except InvalidRowError as exc:
            errors.append(RowError(sheet, number, str(exc)))
            continue
        if record.external_id in seen:
            errors.append(RowError(sheet, number, f"повтор идентификатора {record.external_id}"))
            continue
        seen.add(record.external_id)
        records.append(record)
    return records
