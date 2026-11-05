from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Header, Query, Response, status

from app.api.deps import CurrentUser, SessionDep, SettingsDep
from app.routing import GeoPoint
from app.schemas.catalog import (
    CatalogExport,
    CatalogStatus,
    ExportedOffer,
    OfferRead,
    ProductDetail,
    ProductRead,
    StoreRead,
    StoreWithDistance,
)
from app.schemas.common import error_responses
from app.services import catalog as catalog_service

router = APIRouter(tags=["Каталог"], responses=error_responses(401))

MAX_SEARCH_RESULTS = 10


@router.get("/catalog")
def get_catalog_status(_: CurrentUser, session: SessionDep, settings: SettingsDep) -> CatalogStatus:
    """Какой каталог сейчас загружен. Если is_synthetic = true, цены демонстрационные."""
    active = catalog_service.get_active_import(session)
    if active is None:
        return CatalogStatus(is_loaded=False, offer_max_age_hours=settings.offer_max_age_hours)
    return CatalogStatus(
        is_loaded=True,
        import_id=active.id,
        imported_at=active.created_at,
        is_synthetic=active.is_synthetic,
        stores_count=active.stores_count,
        products_count=active.products_count,
        offers_count=active.offers_count,
        fresh_offers_count=catalog_service.count_fresh_offers(
            session, active.id, datetime.now(UTC), settings.offer_max_age_hours
        ),
        offer_max_age_hours=settings.offer_max_age_hours,
    )


@router.get(
    "/catalog/export",
    responses={304: {"description": "Каталог не менялся"}, **error_responses(503)},
    response_model=CatalogExport,
)
def export_catalog(
    _: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
    response: Response,
    if_none_match: Annotated[str | None, Header()] = None,
) -> CatalogExport | Response:
    """Весь активный каталог для локального кэша приложения: товары, магазины и цены.

    Снимок каталога после публикации не меняется, поэтому его номер служит меткой ETag.
    Клиент присылает её в If-None-Match и, если каталог прежний, получает пустой ответ 304.
    """
    active = catalog_service.require_active_import(session)
    etag = f'"catalog-{active.id}-{settings.offer_max_age_hours}"'
    headers = {"ETag": etag, "Cache-Control": "private, no-cache"}
    if if_none_match == etag:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)

    contents = catalog_service.load_catalog_contents(session, active.id)
    response.headers.update(headers)
    return CatalogExport(
        import_id=active.id,
        imported_at=active.created_at,
        is_synthetic=active.is_synthetic,
        offer_max_age_hours=settings.offer_max_age_hours,
        products=[ProductRead.model_validate(product) for product in contents.products],
        stores=[StoreRead.model_validate(store) for store in contents.stores],
        offers=[ExportedOffer.model_validate(offer) for offer in contents.offers],
    )


@router.get("/products/search")
def search_products(
    _: CurrentUser,
    session: SessionDep,
    q: Annotated[str, Query(min_length=1, max_length=100, description="Текст запроса")],
    limit: Annotated[int, Query(ge=1, le=MAX_SEARCH_RESULTS)] = MAX_SEARCH_RESULTS,
) -> list[ProductRead]:
    """Поиск товара по названию, не больше 10 вариантов (F02).

    Пустой список означает, что ничего не найдено.
    """
    products = catalog_service.search_products(session, q, limit)
    return [ProductRead.model_validate(product) for product in products]


@router.get("/products/{product_id}", responses=error_responses(404))
def get_product(
    product_id: int, _: CurrentUser, session: SessionDep, settings: SettingsDep
) -> ProductDetail:
    """Карточка товара и цены во всех магазинах с отметкой свежести (F04)."""
    product = catalog_service.get_product(session, product_id)
    offers = catalog_service.list_product_offers(
        session, product_id, datetime.now(UTC), settings.offer_max_age_hours
    )
    return ProductDetail(
        **ProductRead.model_validate(product).model_dump(),
        attributes=product.attributes,
        offers=[
            OfferRead(
                store=StoreRead.model_validate(view.offer.store),
                price_kopecks=view.offer.price_kopecks,
                card_price_kopecks=view.offer.card_price_kopecks,
                in_stock=view.offer.in_stock,
                price_type=view.offer.price_type,
                price_conditions=view.offer.price_conditions,
                source_url=view.offer.source_url,
                source_updated_at=view.offer.source_updated_at,
                is_fresh=view.is_fresh,
            )
            for view in offers
        ],
    )


@router.get("/stores")
def list_stores(
    _: CurrentUser,
    session: SessionDep,
    latitude: Annotated[float | None, Query(ge=-90, le=90)] = None,
    longitude: Annotated[float | None, Query(ge=-180, le=180)] = None,
) -> list[StoreWithDistance]:
    """Магазины пилота. Если передать координаты, ближайшие будут первыми."""
    near = GeoPoint(latitude, longitude) if latitude is not None and longitude is not None else None
    return [
        StoreWithDistance(**StoreRead.model_validate(store).model_dump(), distance_meters=distance)
        for store, distance in catalog_service.list_stores(session, near)
    ]
