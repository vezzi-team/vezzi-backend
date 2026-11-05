"""Расчёт планов покупки для корзины пользователя.

Сервис собирает входные данные (корзина, свежие цены, ближайшие магазины,
матрица пешего времени), вызывает чистый планировщик app.planner, строит
линию маршрута и сохраняет до трёх планов, чтобы пользователь мог выбрать один.
"""

import math
import uuid
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import BusinessRuleError, NotFoundError, ServiceUnavailableError
from app.models import Cart, Offer, Plan, PlanItem, PlanStatus, PlanStop, Product, Store, User
from app.planner import optimizer
from app.planner.assignment import cheapest_alternative
from app.planner.models import START, BasketItem, Leg, Place, PriceTable
from app.planner.optimizer import PlanningInput, PlanningProblem, PlanningResult, find_plans
from app.planner.shopping_time import ShoppingTimeModel
from app.routing import GeoPoint, NoRouteError, RoutingError, RoutingProvider, WalkingRoute
from app.schemas.cart import MAX_QUANTITY
from app.schemas.catalog import ProductRead, StoreRead
from app.schemas.planning import (
    Baseline,
    PlanProblem,
    PlanRead,
    PlanRequest,
    PlanResponse,
    Substitution,
)
from app.services import carts, catalog
from app.services import plans as plans_service


@dataclass(frozen=True)
class _Context:
    """Всё, что нужно, чтобы превратить результат планировщика в сохранённые планы."""

    owner_id: uuid.UUID
    cart_id: uuid.UUID
    now: datetime
    data_is_synthetic: bool
    start: GeoPoint
    stores: dict[int, Store]
    products: dict[int, Product]
    offers: dict[tuple[int, int], Offer]
    prices: PriceTable


def calculate_plans(
    session: Session,
    settings: Settings,
    routing: RoutingProvider,
    user: User,
    cart_id: uuid.UUID,
    request: PlanRequest,
    now: datetime,
) -> PlanResponse:
    # 1. Что покупаем и какие цены есть.
    cart = carts.get_owned(session, user, cart_id)
    basket = _basket(session, cart, request.substitutions)
    active_import = catalog.require_active_import(session)
    product_ids = [item.product_id for item in basket]
    all_offers = catalog.load_fresh_offers(
        session, active_import.id, product_ids, now, settings.offer_max_age_hours
    )
    if request.store_ids is not None:
        all_offers = [offer for offer in all_offers if offer.store_id in request.store_ids]

    # 2. Какие магазины рассматриваем.
    start = GeoPoint(request.start.latitude, request.start.longitude)
    candidates = _candidate_stores(all_offers, start, request, settings)
    candidate_ids = {store.id for store in candidates}
    offers = [offer for offer in all_offers if offer.store_id in candidate_ids]
    prices = _price_table(offers)

    context = _Context(
        owner_id=user.id,
        cart_id=cart.id,
        now=now,
        data_is_synthetic=active_import.is_synthetic,
        start=start,
        stores={store.id: store for store in candidates},
        products={
            product.id: product
            for product in session.scalars(select(Product).where(Product.id.in_(product_ids)))
        },
        offers={(offer.product_id, offer.store_id): offer for offer in offers},
        prices=prices,
    )

    # 3. Планировщик выбирает лучшие планы.
    result = find_plans(
        PlanningInput(
            basket=basket,
            prices=prices,
            legs=_travel_legs(routing, start, candidates),
            max_stores=request.max_stores,
            max_total_seconds=request.max_total_minutes * 60,
            shopping_time=_shopping_time_model(settings),
            store_formats={store.id: store.format.value for store in candidates},
        )
    )

    required_radius = None
    if result.problem is PlanningProblem.ITEMS_UNAVAILABLE and request.radius_meters is not None:
        required_radius = _radius_to_cover(product_ids, all_offers, start)
        if required_radius is not None and required_radius > request.radius_meters:
            result = replace(result, problem=PlanningProblem.RADIUS_TOO_SMALL)

    # 4. Строим линии маршрутов и сохраняем планы.
    routed = _with_routes(routing, result.plans, context)
    if result.plans and not routed:
        result = PlanningResult(plans=[], baseline=None, problem=PlanningProblem.ROUTE_UNAVAILABLE)

    saved = [
        _to_model(plan, route, rank, result.baseline, routing, context)
        for rank, (plan, route) in enumerate(routed, start=1)
    ]
    plans_service.replace_proposals(session, cart, saved)

    return PlanResponse(
        status="ok" if saved else "no_plans",
        plans=[PlanRead.model_validate(plan) for plan in saved],
        baseline=_baseline(result.baseline, context) if saved else None,
        problem=_problem(result, context, required_radius),
        calculated_at=now,
        offer_max_age_hours=settings.offer_max_age_hours,
        data_is_synthetic=active_import.is_synthetic,
    )


def _basket(
    session: Session, cart: Cart, substitutions: Sequence[Substitution]
) -> list[BasketItem]:
    """Позиции корзины с учётом подтверждённых пользователем замен."""
    quantities = {item.product_id: item.quantity for item in cart.items}
    if not quantities:
        raise BusinessRuleError("Корзина пуста", code="cart_empty")

    for substitution in substitutions:
        if substitution.product_id not in quantities:
            raise BusinessRuleError(
                f"Товара {substitution.product_id} нет в корзине", code="invalid_substitution"
            )
        if session.get(Product, substitution.replacement_product_id) is None:
            raise NotFoundError("Товар для замены не найден", code="product_not_found")
        quantity = quantities.pop(substitution.product_id)
        replacement = substitution.replacement_product_id
        quantities[replacement] = min(MAX_QUANTITY, quantities.get(replacement, 0) + quantity)

    return [BasketItem(product_id, quantity) for product_id, quantity in quantities.items()]


def _candidate_stores(
    offers: Sequence[Offer], start: GeoPoint, request: PlanRequest, settings: Settings
) -> list[Store]:
    """Ближайшие магазины внутри радиуса. Их число ограничено, чтобы перебор оставался быстрым."""
    stores = catalog.store_distance_order(
        {offer.store for offer in offers}, start, max_meters=request.radius_meters
    )
    return stores[: settings.planner_candidate_stores]


def _price_table(offers: Sequence[Offer]) -> dict[int, dict[int, int]]:
    prices: dict[int, dict[int, int]] = defaultdict(dict)
    for offer in offers:
        prices[offer.product_id][offer.store_id] = offer.price_kopecks
    return prices


def _radius_to_cover(
    product_ids: Sequence[int], offers: Sequence[Offer], start: GeoPoint
) -> int | None:
    """Радиус, внутри которого каждый товар продаётся хотя бы в одном магазине.

    None, если какой-то товар не продаётся нигде: тогда дело не в радиусе.
    """
    nearest: dict[int, float] = {}
    for offer in offers:
        distance = catalog.distance_meters(start, offer.store)
        nearest[offer.product_id] = min(distance, nearest.get(offer.product_id, math.inf))
    if any(product_id not in nearest for product_id in product_ids):
        return None
    return math.ceil(max(nearest[product_id] for product_id in product_ids))


def _travel_legs(
    routing: RoutingProvider, start: GeoPoint, stores: Sequence[Store]
) -> dict[tuple[Place, Place], Leg]:
    if not stores:
        return {}
    store_points = [GeoPoint(store.latitude, store.longitude) for store in stores]
    try:
        matrix = routing.walking_matrix(origins=[start, *store_points], destinations=store_points)
    except NoRouteError:
        return {}  # старт или магазины далеко от пешеходных дорог: планировщик сообщит об этом
    except RoutingError as exc:
        raise _routing_unavailable() from exc

    origins: list[Place] = [START, *(store.id for store in stores)]
    legs: dict[tuple[Place, Place], Leg] = {}
    for row, origin in enumerate(origins):
        for column, store in enumerate(stores):
            seconds = matrix.seconds[row][column]
            meters = matrix.meters[row][column]
            if origin != store.id and seconds is not None and meters is not None:
                legs[(origin, store.id)] = Leg(seconds, meters)
    return legs


def _with_routes(
    routing: RoutingProvider, plans: Sequence[optimizer.Plan], context: _Context
) -> list[tuple[optimizer.Plan, WalkingRoute]]:
    """Достраивает линию маршрута. План без настоящего пути исключается (F09)."""
    routed = []
    for plan in plans:
        waypoints = [
            context.start,
            *(
                GeoPoint(context.stores[i].latitude, context.stores[i].longitude)
                for i in plan.store_ids
            ),
        ]
        try:
            route = routing.walking_route(waypoints)
        except NoRouteError:
            continue
        except RoutingError as exc:
            raise _routing_unavailable() from exc
        routed.append((plan, route))
    return routed


def _to_model(
    plan: optimizer.Plan,
    route: WalkingRoute,
    rank: int,
    baseline: optimizer.Plan | None,
    routing: RoutingProvider,
    context: _Context,
) -> Plan:
    return Plan(
        owner_id=context.owner_id,
        cart_id=context.cart_id,
        status=PlanStatus.PLANNED,
        rank=rank,
        total_kopecks=plan.total_kopecks,
        savings_kopecks=optimizer.savings_kopecks(plan, baseline),
        walking_seconds=plan.walking_seconds,
        walking_meters=plan.walking_meters,
        shopping_seconds=plan.shopping_seconds,
        route_provider=routing.name,
        route_uses_road_network=routing.uses_road_network,
        route_points=[{"latitude": p.latitude, "longitude": p.longitude} for p in route.points],
        data_is_synthetic=context.data_is_synthetic,
        created_at=context.now,
        stops=[
            PlanStop(
                position=position,
                store=context.stores[visit.store_id],
                subtotal_kopecks=visit.subtotal_kopecks,
                shopping_seconds=visit.shopping_seconds,
                walk_from_previous_seconds=visit.walk_from_previous.seconds,
                walk_from_previous_meters=visit.walk_from_previous.meters,
                items=[
                    _item_model(item.product_id, item.quantity, visit.store_id, plan, context)
                    for item in visit.items
                ],
            )
            for position, visit in enumerate(plan.visits, start=1)
        ],
    )


def _item_model(
    product_id: int, quantity: int, store_id: int, plan: optimizer.Plan, context: _Context
) -> PlanItem:
    offer = context.offers[(product_id, store_id)]
    alternative = cheapest_alternative(product_id, context.prices, plan.store_ids, store_id)
    return PlanItem(
        product=context.products[product_id],
        quantity=quantity,
        unit_price_kopecks=offer.price_kopecks,
        card_price_kopecks=offer.card_price_kopecks,
        price_type=offer.price_type,
        price_conditions=offer.price_conditions,
        price_updated_at=offer.source_updated_at,
        alternative_store_id=alternative[0] if alternative else None,
        alternative_price_kopecks=alternative[1] if alternative else None,
    )


def _baseline(baseline: optimizer.Plan | None, context: _Context) -> Baseline | None:
    if baseline is None:
        return None
    store = context.stores[baseline.store_ids[0]]
    return Baseline(store=StoreRead.model_validate(store), total_kopecks=baseline.total_kopecks)


def _problem(
    result: PlanningResult, context: _Context, required_radius: int | None
) -> PlanProblem | None:
    if result.problem is None:
        return None
    match result.problem:
        case PlanningProblem.ITEMS_UNAVAILABLE:
            message = "Некоторые товары сейчас нигде не продаются по актуальной цене"
        case PlanningProblem.STORE_LIMIT_TOO_LOW:
            needed = result.min_required_stores
            message = (
                f"Чтобы купить всё, нужно магазинов: {needed}. Увеличьте лимит или уберите товары"
                if needed
                else "Собрать всю корзину в доступных магазинах не получается"
            )
        case PlanningProblem.TIME_LIMIT_TOO_LOW:
            message = "Не хватает времени: самый быстрый полный план дольше лимита"
        case PlanningProblem.ROUTE_UNAVAILABLE:
            message = "Не удалось построить пешеходный маршрут до магазинов"
        case PlanningProblem.RADIUS_TOO_SMALL:
            message = "В выбранном радиусе продаются не все товары. Увеличьте радиус"
    return PlanProblem(
        reason=result.problem,
        message=message,
        unavailable_products=[
            ProductRead.model_validate(context.products[product_id])
            for product_id in result.unavailable_product_ids
        ],
        min_required_stores=result.min_required_stores,
        min_required_minutes=(
            math.ceil(result.min_required_seconds / 60) if result.min_required_seconds else None
        ),
        min_required_radius_meters=(
            required_radius if result.problem is PlanningProblem.RADIUS_TOO_SMALL else None
        ),
    )


def _shopping_time_model(settings: Settings) -> ShoppingTimeModel:
    return ShoppingTimeModel(
        min_visit_seconds=settings.shopping_min_visit_seconds,
        base_seconds=settings.shopping_base_seconds,
        seconds_per_position=settings.shopping_seconds_per_position,
        seconds_per_unit=settings.shopping_seconds_per_unit,
    )


def _routing_unavailable() -> ServiceUnavailableError:
    return ServiceUnavailableError(
        "Сервис маршрутов временно недоступен, попробуйте ещё раз", code="routing_unavailable"
    )
