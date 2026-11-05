"""Сравнение корзины по сетям: сколько стоит вся корзина в каждой сети.

В суммы идут те же цены, что и в расчёте планов: свежие, в наличии, в работающих магазинах.
Устаревшие цены и товары без наличия видны в строках, но в суммы не входят.
Сама арифметика в app/planner/chain_totals.py.
"""

import uuid
from collections.abc import Mapping, Sequence
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import BusinessRuleError
from app.models import Offer, Product, Store, User
from app.planner.chain_totals import ChainLine, ChainOffer, ChainTotal, chain_totals
from app.planner.models import BasketItem
from app.schemas.catalog import ProductRead, StoreRead
from app.schemas.comparison import ChainComparison, ChainLineRead, ChainTotalRead
from app.services import carts, catalog


def compare_chains(
    session: Session,
    settings: Settings,
    user: User,
    cart_id: uuid.UUID,
    chains: Sequence[str] | None,
    now: datetime,
) -> ChainComparison:
    cart = carts.get_owned(session, user, cart_id)
    basket = [BasketItem(item.product_id, item.quantity) for item in cart.items]
    if not basket:
        raise BusinessRuleError("Корзина пуста", code="cart_empty")

    active_import = catalog.require_active_import(session)
    stores = {
        store.id: store for store in session.scalars(select(Store).where(Store.is_active.is_(True)))
    }
    if chains:
        unknown = sorted(set(chains) - {store.chain for store in stores.values()})
        if unknown:
            raise BusinessRuleError(
                f"Нет таких сетей: {', '.join(unknown)}", code="unknown_chain", details=unknown
            )
    store_chains = {
        store.id: store.chain for store in stores.values() if not chains or store.chain in chains
    }

    product_ids = [item.product_id for item in basket]
    products = {
        product.id: ProductRead.model_validate(product)
        for product in session.scalars(select(Product).where(Product.id.in_(product_ids)))
    }
    cutoff = catalog.freshness_cutoff(now, settings.offer_max_age_hours)
    offers = [
        _chain_offer(offer, cutoff)
        for offer in catalog.load_offers(session, active_import.id, product_ids)
    ]

    return ChainComparison(
        chains=[
            _chain_read(total, products, stores)
            for total in chain_totals(basket, offers, store_chains)
        ],
        calculated_at=now,
        offer_max_age_hours=settings.offer_max_age_hours,
        data_is_synthetic=active_import.is_synthetic,
    )


def _chain_offer(offer: Offer, cutoff: datetime) -> ChainOffer:
    return ChainOffer(
        product_id=offer.product_id,
        store_id=offer.store_id,
        price_kopecks=offer.price_kopecks,
        observed_at=offer.source_updated_at,
        in_stock=offer.in_stock,
        is_fresh=offer.source_updated_at >= cutoff,
        card_price_kopecks=offer.card_price_kopecks,
        price_type=offer.price_type,
        price_conditions=offer.price_conditions,
    )


def _chain_read(
    total: ChainTotal, products: Mapping[int, ProductRead], stores: Mapping[int, Store]
) -> ChainTotalRead:
    return ChainTotalRead(
        chain=total.chain,
        is_complete=total.is_complete,
        total_kopecks=total.total_kopecks,
        found_total_kopecks=total.found_total_kopecks,
        items_count=len(total.lines),
        found_items_count=total.found_items_count,
        coverage_percent=total.coverage_percent,
        missing_products=[products[i] for i in total.missing_product_ids],
        oldest_price_updated_at=total.oldest_observed_at,
        lines=[_line_read(line, products, stores) for line in total.lines],
    )


def _line_read(
    line: ChainLine, products: Mapping[int, ProductRead], stores: Mapping[int, Store]
) -> ChainLineRead:
    offer = line.offer
    return ChainLineRead(
        product=products[line.product_id],
        quantity=line.quantity,
        status=line.status,
        unit_price_kopecks=offer.price_kopecks if offer else None,
        total_kopecks=line.total_kopecks,
        card_price_kopecks=offer.card_price_kopecks if offer else None,
        price_type=offer.price_type if offer else None,
        price_conditions=offer.price_conditions if offer else None,
        store=StoreRead.model_validate(stores[offer.store_id]) if offer else None,
        price_updated_at=offer.observed_at if offer else None,
        is_fresh=offer.is_fresh if offer else None,
    )
