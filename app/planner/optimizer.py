"""Поиск планов покупки (F07, F08, F09, F11).

Алгоритм:
1. Перебираем все наборы магазинов размером от 1 до max_stores.
2. В каждом наборе раздаём товары по самым низким ценам (assign_cheapest).
   Неполные корзины отбрасываем, неиспользованные магазины убираем из набора.
3. Для набора ищем самый быстрый порядок обхода и добавляем время покупок.
4. Оставляем планы, которые укладываются в лимит времени, сортируем по цене,
   затем по времени и числу магазинов, и отдаём до трёх лучших.
5. База для экономии: самый дешёвый допустимый план в одном магазине.

Мы не заявляем глобальный оптимум: план лучший среди описанных кандидатов (как требует F07).
"""

import enum
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import combinations

from app.planner.assignment import AssignedItem, assign_cheapest
from app.planner.models import BasketItem, Leg, PriceTable, TravelLegs
from app.planner.shopping_time import ShoppingTimeModel
from app.planner.visit_order import best_visit_order

MAX_PLANS = 3


class PlanningProblem(enum.StrEnum):
    ITEMS_UNAVAILABLE = "items_unavailable"
    STORE_LIMIT_TOO_LOW = "store_limit_too_low"
    TIME_LIMIT_TOO_LOW = "time_limit_too_low"
    ROUTE_UNAVAILABLE = "route_unavailable"
    # Ставит сервис, а не планировщик: про радиус на карте алгоритм не знает.
    RADIUS_TOO_SMALL = "radius_too_small"


@dataclass(frozen=True)
class StoreVisit:
    store_id: int
    items: tuple[AssignedItem, ...]
    walk_from_previous: Leg
    shopping_seconds: int

    @property
    def subtotal_kopecks(self) -> int:
        return sum(item.total_kopecks for item in self.items)


@dataclass(frozen=True)
class Plan:
    visits: tuple[StoreVisit, ...]

    @property
    def store_ids(self) -> tuple[int, ...]:
        return tuple(visit.store_id for visit in self.visits)

    @property
    def total_kopecks(self) -> int:
        return sum(visit.subtotal_kopecks for visit in self.visits)

    @property
    def walking_seconds(self) -> int:
        return sum(visit.walk_from_previous.seconds for visit in self.visits)

    @property
    def walking_meters(self) -> int:
        return sum(visit.walk_from_previous.meters for visit in self.visits)

    @property
    def shopping_seconds(self) -> int:
        return sum(visit.shopping_seconds for visit in self.visits)

    @property
    def total_seconds(self) -> int:
        return self.walking_seconds + self.shopping_seconds

    def sort_key(self) -> tuple[int, int, int, tuple[int, ...]]:
        return (
            self.total_kopecks,
            self.total_seconds,
            len(self.visits),
            tuple(sorted(self.store_ids)),
        )


@dataclass(frozen=True)
class PlanningInput:
    basket: Sequence[BasketItem]
    prices: PriceTable
    legs: TravelLegs
    max_stores: int
    max_total_seconds: int
    shopping_time: ShoppingTimeModel
    store_formats: Mapping[int, str]


@dataclass(frozen=True)
class PlanningResult:
    plans: list[Plan]
    baseline: Plan | None
    problem: PlanningProblem | None = None
    unavailable_product_ids: tuple[int, ...] = ()
    min_required_stores: int | None = None
    min_required_seconds: int | None = None


def savings_kopecks(plan: Plan, baseline: Plan | None) -> int | None:
    """Экономия относительно базового плана. None, если базы нет или план дороже неё."""
    if baseline is None:
        return None
    difference = baseline.total_kopecks - plan.total_kopecks
    return difference if difference >= 0 else None


def find_plans(data: PlanningInput) -> PlanningResult:
    unavailable = tuple(
        item.product_id for item in data.basket if not data.prices.get(item.product_id)
    )
    if unavailable:
        return PlanningResult(
            plans=[],
            baseline=None,
            problem=PlanningProblem.ITEMS_UNAVAILABLE,
            unavailable_product_ids=unavailable,
        )

    candidates = sorted({store_id for offers in data.prices.values() for store_id in offers})
    complete_plans, some_route_missing = _complete_plans(data, candidates)

    if not complete_plans:
        if some_route_missing:
            return PlanningResult([], None, problem=PlanningProblem.ROUTE_UNAVAILABLE)
        return PlanningResult(
            [],
            None,
            problem=PlanningProblem.STORE_LIMIT_TOO_LOW,
            min_required_stores=_min_stores_to_cover(data, candidates),
        )

    feasible = sorted(
        (plan for plan in complete_plans if plan.total_seconds <= data.max_total_seconds),
        key=Plan.sort_key,
    )
    if not feasible:
        return PlanningResult(
            [],
            None,
            problem=PlanningProblem.TIME_LIMIT_TOO_LOW,
            min_required_seconds=min(plan.total_seconds for plan in complete_plans),
        )

    baseline = next((plan for plan in feasible if len(plan.visits) == 1), None)
    return PlanningResult(plans=feasible[:MAX_PLANS], baseline=baseline)


def _complete_plans(data: PlanningInput, candidates: list[int]) -> tuple[list[Plan], bool]:
    plans = []
    seen_store_sets: set[frozenset[int]] = set()
    some_route_missing = False

    for size in range(1, min(data.max_stores, len(candidates)) + 1):
        for subset in combinations(candidates, size):
            assignment = assign_cheapest(data.basket, data.prices, subset)
            if assignment is None:
                continue
            used_stores = frozenset(item.store_id for item in assignment)
            if used_stores in seen_store_sets:
                continue
            seen_store_sets.add(used_stores)

            plan = _build_plan(data, assignment, used_stores)
            if plan is None:
                some_route_missing = True
            else:
                plans.append(plan)

    return plans, some_route_missing


def _build_plan(
    data: PlanningInput, assignment: list[AssignedItem], stores: frozenset[int]
) -> Plan | None:
    route = best_visit_order(stores, data.legs)
    if route is None:
        return None

    visits = []
    for store_id, leg in zip(route.store_order, route.legs, strict=True):
        items = tuple(item for item in assignment if item.store_id == store_id)
        shopping = data.shopping_time.visit_seconds(
            positions=len(items),
            units=sum(item.quantity for item in items),
            store_format=data.store_formats.get(store_id, "supermarket"),
        )
        visits.append(StoreVisit(store_id, items, leg, shopping))
    return Plan(tuple(visits))


def _min_stores_to_cover(data: PlanningInput, candidates: list[int]) -> int | None:
    """Сколько магазинов нужно, чтобы собрать всю корзину (без учёта маршрута)."""
    for size in range(data.max_stores + 1, len(candidates) + 1):
        for subset in combinations(candidates, size):
            if assign_cheapest(data.basket, data.prices, subset) is not None:
                return size
    return None
