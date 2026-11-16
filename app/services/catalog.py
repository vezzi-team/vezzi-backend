"""Чтение каталога: поиск товаров, карточка с ценами, магазины, свежие предложения."""

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from smartcart_ml.text import normalize
from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import Session, joinedload

from app.core.errors import NotFoundError, ServiceUnavailableError
from app.models import CatalogImport, ImportStatus, Offer, Product, Store
from app.routing import GeoPoint
from app.routing.geo import haversine_meters
from app.services import ml_matcher

# Оценка ML-модуля ниже 0,2 означает случайное совпадение букв: на бессмысленных запросах
# вроде «йцукен» лучший результат почти всегда ниже. Как выбран порог: docs/decisions.md.
MIN_SEARCH_SCORE = 0.2


@dataclass(frozen=True)
class OfferView:
    offer: Offer
    is_fresh: bool


@dataclass(frozen=True)
class CatalogContents:
    products: Sequence[Product]
    stores: Sequence[Store]
    offers: Sequence[Offer]


def freshness_cutoff(now: datetime, max_age_hours: int) -> datetime:
    """Предложение свежее, если source_updated_at >= cutoff. Ровно 24 часа ещё допустимо."""
    return now - timedelta(hours=max_age_hours)


def get_active_import(session: Session) -> CatalogImport | None:
    return session.scalar(select(CatalogImport).where(CatalogImport.status == ImportStatus.ACTIVE))


def require_active_import(session: Session) -> CatalogImport:
    active = get_active_import(session)
    if active is None:
        raise ServiceUnavailableError("Каталог ещё не загружен", code="catalog_not_loaded")
    return active


def search_products(session: Session, query: str, limit: int) -> list[Product]:
    """Поиск по названию через ML-модуль команды. Он сравнивает буквосочетания, поэтому
    находит товар и с опечаткой: «кифир», «тварог».

    Ищем только среди товаров, которые продаются в активном каталоге: товары из
    прошлых загрузок остаются в базе ради старых планов, но предлагать их не нужно.
    """
    active = get_active_import(session)
    # Запрос из одних знаков препинания модуль не принимает: искать в нём нечего.
    if active is None or not normalize(query):
        return []
    found = ml_matcher.matcher_for(session, active).search(query, top_k=limit)
    ids = [row["product_id"] for row in found if row["score"] >= MIN_SEARCH_SCORE]
    products = {
        product.id: product
        for product in session.scalars(select(Product).where(Product.id.in_(ids)))
    }
    return [products[product_id] for product_id in ids]


def load_catalog_contents(session: Session, import_id: int) -> CatalogContents:
    """Всё содержимое снимка: работающие магазины, их цены и товары с этими ценами."""
    stores = session.scalars(
        select(Store).where(Store.is_active.is_(True)).order_by(Store.id)
    ).all()
    offers = session.scalars(
        select(Offer)
        .join(Store)
        .where(Offer.import_id == import_id, Store.is_active.is_(True))
        .order_by(Offer.id)
    ).all()
    product_ids = {offer.product_id for offer in offers}
    products = session.scalars(
        select(Product).where(Product.id.in_(product_ids)).order_by(Product.id)
    ).all()
    return CatalogContents(products, stores, offers)


def get_product(session: Session, product_id: int) -> Product:
    product = session.get(Product, product_id)
    if product is None:
        raise NotFoundError("Товар не найден", code="product_not_found")
    return product


def list_product_offers(
    session: Session, product_id: int, now: datetime, max_age_hours: int
) -> list[OfferView]:
    active = get_active_import(session)
    if active is None:
        return []
    offers = session.scalars(
        select(Offer)
        .options(joinedload(Offer.store))
        .join(Store)
        .where(Offer.import_id == active.id, Offer.product_id == product_id, Store.is_active)
        .order_by(Offer.price_kopecks, Offer.store_id)
    )
    cutoff = freshness_cutoff(now, max_age_hours)
    return [
        OfferView(offer, is_fresh=offer.source_updated_at >= cutoff and offer.in_stock is True)
        for offer in offers
    ]


def list_stores(session: Session, near: GeoPoint | None = None) -> list[tuple[Store, int | None]]:
    stores = session.scalars(select(Store).where(Store.is_active).order_by(Store.id)).all()
    if near is None:
        return [(store, None) for store in stores]
    with_distance = [(store, round(haversine_meters(near, _point(store)))) for store in stores]
    return sorted(with_distance, key=lambda pair: (pair[1], pair[0].id))


def load_fresh_offers(
    session: Session,
    import_id: int,
    product_ids: Collection[int],
    now: datetime,
    max_age_hours: int,
) -> list[Offer]:
    """Предложения, которые участвуют в расчёте: свежие, в наличии, в работающих магазинах (F04)."""
    statement = (
        select(Offer)
        .options(joinedload(Offer.store))
        .join(Store)
        .where(
            Offer.import_id == import_id,
            Offer.product_id.in_(product_ids),
            *_usable_for_planning(now, max_age_hours),
        )
    )
    return list(session.scalars(statement))


def load_offers(session: Session, import_id: int, product_ids: Collection[int]) -> list[Offer]:
    """Все цены на товары в работающих магазинах, в том числе устаревшие и без наличия."""
    statement = (
        select(Offer)
        .join(Store)
        .where(
            Offer.import_id == import_id,
            Offer.product_id.in_(product_ids),
            Store.is_active.is_(True),
        )
    )
    return list(session.scalars(statement))


def count_fresh_offers(session: Session, import_id: int, now: datetime, max_age_hours: int) -> int:
    """Сколько цен снимка сейчас участвует в расчёте. Если мало, данные устарели."""
    statement = (
        select(func.count())
        .select_from(Offer)
        .join(Store)
        .where(Offer.import_id == import_id, *_usable_for_planning(now, max_age_hours))
    )
    return session.scalar(statement) or 0


def cheapest_fresh_prices(
    session: Session, import_id: int, now: datetime, max_age_hours: int
) -> dict[int, int]:
    """Самая низкая цена каждого товара среди тех, что участвуют в расчёте."""
    statement = (
        select(Offer.product_id, func.min(Offer.price_kopecks))
        .join(Store)
        .where(Offer.import_id == import_id, *_usable_for_planning(now, max_age_hours))
        .group_by(Offer.product_id)
    )
    return {product_id: price for product_id, price in session.execute(statement).all()}


def _usable_for_planning(now: datetime, max_age_hours: int) -> list[ColumnElement[bool]]:
    return [
        Offer.in_stock.is_(True),
        Offer.source_updated_at >= freshness_cutoff(now, max_age_hours),
        Store.is_active.is_(True),
    ]


def distance_meters(start: GeoPoint, store: Store) -> float:
    """Расстояние по прямой. Для пешего пути есть маршрутизатор, это только для отбора магазинов."""
    return haversine_meters(start, _point(store))


def store_distance_order(
    stores: Collection[Store], start: GeoPoint, max_meters: int | None = None
) -> list[Store]:
    """Магазины от ближнего к дальнему. С max_meters только те, что не дальше этого расстояния."""
    ordered = sorted(stores, key=lambda store: (distance_meters(start, store), store.id))
    if max_meters is None:
        return ordered
    return [store for store in ordered if distance_meters(start, store) <= max_meters]


def _point(store: Store) -> GeoPoint:
    return GeoPoint(store.latitude, store.longitude)
