"""Публикация проверенного каталога в базу одной транзакцией.

Порядок: обновить магазины и товары по external_id, перевести прошлый активный
снимок в архив, создать новый снимок и записать его предложения. Если на любом
шаге случится ошибка, транзакция откатится и активным останется прошлый снимок.
"""

import uuid
from collections.abc import Iterable
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta
from typing import Any, Literal

from sqlalchemy import insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.catalog_import.columns import OFFERS_SHEET
from app.catalog_import.reader import CatalogFormatError
from app.catalog_import.records import OfferRecord, ParsedCatalog, RowError
from app.models import CatalogImport, ImportStatus, Offer, Product, Store

FUTURE_TOLERANCE = timedelta(minutes=5)
UPSERT_CHUNK_SIZE = 1000
MAX_REPORTED_ERRORS = 200


@dataclass(frozen=True)
class ImportReport:
    status: Literal["published", "unchanged"]
    import_id: int
    stores_count: int
    products_count: int
    offers_count: int
    rejected_rows_count: int
    is_synthetic: bool
    timestamps_shifted: bool
    skipped_weighted_products: int
    skipped_weighted_offers: int
    errors: list[RowError]


def publish_catalog(
    session: Session,
    catalog: ParsedCatalog,
    *,
    source_name: str,
    file_sha256: str,
    now: datetime,
    imported_by_id: uuid.UUID | None = None,
    shift_timestamps: bool = False,
    mark_synthetic: bool = False,
) -> ImportReport:
    """Публикует каталог. mark_synthetic помечает данные как демонстрационные,
    даже если в файле data_origin не равен synthetic.
    """
    is_synthetic = catalog.is_synthetic or mark_synthetic
    active = session.scalar(
        select(CatalogImport).where(CatalogImport.status == ImportStatus.ACTIVE)
    )
    if (
        active is not None
        and active.file_sha256 == file_sha256
        and active.is_synthetic == is_synthetic
        and not shift_timestamps
    ):
        return _report("unchanged", active, catalog, catalog.errors)

    offers = _shift_to_now(catalog.offers, now) if shift_timestamps else catalog.offers
    offers, future_errors = _reject_future(offers, now)
    errors = catalog.errors + future_errors
    if not offers:
        raise CatalogFormatError("В файле нет ни одной корректной строки с ценой")

    try:
        store_ids = _upsert(session, Store, [asdict(store) for store in catalog.stores])
        product_ids = _upsert(session, Product, [asdict(product) for product in catalog.products])

        if active is not None:
            active.status = ImportStatus.ARCHIVED
            session.flush()

        snapshot = CatalogImport(
            status=ImportStatus.ACTIVE,
            source_name=source_name,
            file_sha256=file_sha256,
            is_synthetic=is_synthetic,
            timestamps_shifted=shift_timestamps,
            stores_count=len(catalog.stores),
            products_count=len(catalog.products),
            offers_count=len(offers),
            rejected_rows_count=len(errors),
            imported_by_id=imported_by_id,
        )
        session.add(snapshot)
        session.flush()

        session.execute(
            insert(Offer),
            [_offer_row(offer, snapshot.id, store_ids, product_ids) for offer in offers],
        )
        session.commit()
    except Exception:
        session.rollback()
        raise

    return _report("published", snapshot, catalog, errors)


def _offer_row(
    offer: OfferRecord, import_id: int, store_ids: dict[str, int], product_ids: dict[str, int]
) -> dict[str, Any]:
    return {
        "import_id": import_id,
        "store_id": store_ids[offer.store_external_id],
        "product_id": product_ids[offer.product_external_id],
        "price_kopecks": offer.price_kopecks,
        "card_price_kopecks": offer.card_price_kopecks,
        "in_stock": offer.in_stock,
        "price_type": offer.price_type,
        "price_conditions": offer.price_conditions,
        "source_product_id": offer.source_product_id,
        "source_url": offer.source_url,
        "source_updated_at": offer.source_updated_at,
    }


def _upsert(
    session: Session, model: type[Store] | type[Product], rows: list[dict[str, Any]]
) -> dict[str, int]:
    """INSERT ... ON CONFLICT (external_id) DO UPDATE. Возвращает {external_id: id}."""
    ids: dict[str, int] = {}
    for start in range(0, len(rows), UPSERT_CHUNK_SIZE):
        chunk = rows[start : start + UPSERT_CHUNK_SIZE]
        insert_rows = pg_insert(model).values(chunk)
        updated_columns = {
            name: insert_rows.excluded[name] for name in chunk[0] if name != "external_id"
        }
        upsert = insert_rows.on_conflict_do_update(
            index_elements=["external_id"], set_=updated_columns
        ).returning(model.id, model.external_id)
        ids.update({external_id: id_ for id_, external_id in session.execute(upsert)})
    return ids


def _shift_to_now(offers: list[OfferRecord], now: datetime) -> list[OfferRecord]:
    """Сдвигает время всех цен так, чтобы самая свежая была обновлена «сейчас».

    Нужно только для синтетических данных: черновик каталога быстро устаревает
    по правилу 24 часов, а для демонстрации нужны свежие цены.
    """
    if not offers:
        return offers
    delta = now - max(offer.source_updated_at for offer in offers)
    return [replace(offer, source_updated_at=offer.source_updated_at + delta) for offer in offers]


def _reject_future(
    offers: Iterable[OfferRecord], now: datetime
) -> tuple[list[OfferRecord], list[RowError]]:
    accepted, errors = [], []
    for offer in offers:
        if offer.source_updated_at > now + FUTURE_TOLERANCE:
            errors.append(RowError(OFFERS_SHEET, offer.row, "время обновления цены в будущем"))
        else:
            accepted.append(offer)
    return accepted, errors


def _report(
    status: Literal["published", "unchanged"],
    snapshot: CatalogImport,
    catalog: ParsedCatalog,
    errors: list[RowError],
) -> ImportReport:
    return ImportReport(
        status=status,
        import_id=snapshot.id,
        stores_count=snapshot.stores_count,
        products_count=snapshot.products_count,
        offers_count=snapshot.offers_count,
        rejected_rows_count=len(errors),
        is_synthetic=snapshot.is_synthetic,
        timestamps_shifted=snapshot.timestamps_shifted,
        skipped_weighted_products=catalog.skipped_weighted_products,
        skipped_weighted_offers=catalog.skipped_weighted_offers,
        errors=errors[:MAX_REPORTED_ERRORS],
    )
