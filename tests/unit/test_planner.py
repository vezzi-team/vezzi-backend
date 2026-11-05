from dataclasses import replace
from itertools import permutations
from typing import ClassVar

import pytest

from app.planner.assignment import assign_cheapest, cheapest_alternative
from app.planner.models import START, BasketItem, Leg
from app.planner.optimizer import PlanningInput, PlanningProblem, find_plans, savings_kopecks
from app.planner.shopping_time import ShoppingTimeModel
from app.planner.visit_order import best_visit_order, walk

M1, M2 = 1, 2
A, B = 101, 102


def minutes(value: int) -> Leg:
    return Leg(seconds=value * 60, meters=value * 80)


def reference_input(max_total_minutes: int) -> PlanningInput:
    """Контрольный пример из раздела 9.2 ТЗ."""
    return PlanningInput(
        basket=[BasketItem(A, 2), BasketItem(B, 1)],
        prices={A: {M1: 10000, M2: 9000}, B: {M1: 15000, M2: 18000}},
        legs={
            (START, M1): minutes(8),
            (START, M2): minutes(12),
            (M1, M2): minutes(6),
            (M2, M1): minutes(6),
        },
        max_stores=5,
        max_total_seconds=max_total_minutes * 60,
        shopping_time=ShoppingTimeModel(),
        store_formats={},
    )


class TestReferenceExample:
    def test_mixed_plan_is_cheapest_when_time_allows(self) -> None:
        result = find_plans(reference_input(max_total_minutes=60))

        assert [plan.total_kopecks for plan in result.plans] == [33000, 35000, 36000]
        mixed = result.plans[0]
        assert mixed.store_ids == (M1, M2)
        assert mixed.walking_seconds == 14 * 60
        assert mixed.shopping_seconds == 20 * 60
        assert mixed.total_seconds == 34 * 60

        assert result.baseline is not None
        assert result.baseline.store_ids == (M1,)
        assert savings_kopecks(mixed, result.baseline) == 2000

    def test_mixed_plan_is_excluded_with_30_minute_limit(self) -> None:
        result = find_plans(reference_input(max_total_minutes=30))

        assert [plan.store_ids for plan in result.plans] == [(M1,), (M2,)]
        assert result.plans[0].total_seconds == 18 * 60
        assert savings_kopecks(result.plans[0], result.baseline) == 0
        assert savings_kopecks(result.plans[1], result.baseline) is None


class TestShoppingTime:
    model = ShoppingTimeModel()

    @pytest.mark.parametrize(("positions", "units"), [(1, 1), (2, 3), (4, 4)])
    def test_small_purchase_takes_minimum_visit(self, positions: int, units: int) -> None:
        assert self.model.visit_seconds(positions, units) == 600

    def test_grows_with_positions_and_units(self) -> None:
        assert self.model.visit_seconds(10, 15) == 300 + 600 + 75
        assert self.model.visit_seconds(30, 60) == 300 + 1800 + 300

    def test_store_format_changes_search_time(self) -> None:
        convenience = self.model.visit_seconds(20, 20, "convenience")
        supermarket = self.model.visit_seconds(20, 20, "supermarket")
        hypermarket = self.model.visit_seconds(20, 20, "hypermarket")
        assert convenience < supermarket < hypermarket
        assert hypermarket == 300 + 20 * 60 * 140 // 100 + 100


class TestAssignment:
    def test_equal_prices_resolved_by_smaller_store_id(self) -> None:
        assigned = assign_cheapest([BasketItem(A, 1)], {A: {7: 5000, 3: 5000}}, stores={3, 7})
        assert assigned is not None
        assert assigned[0].store_id == 3

    def test_returns_none_when_item_not_sold_in_subset(self) -> None:
        assert assign_cheapest([BasketItem(A, 1)], {A: {7: 5000}}, stores={3}) is None

    def test_line_total_uses_integer_kopecks(self) -> None:
        assigned = assign_cheapest([BasketItem(A, 3)], {A: {1: 3333}}, stores={1})
        assert assigned is not None
        assert assigned[0].total_kopecks == 9999


class TestVisitOrder:
    def test_route_starts_at_start_and_does_not_return(self) -> None:
        legs = {(START, 1): minutes(5), (1, 2): minutes(5), (2, START): minutes(1)}
        route = walk([1, 2], legs)
        assert route is not None
        assert route.seconds == 10 * 60

    def test_missing_leg_makes_order_impossible(self) -> None:
        assert walk([1, 2], {(START, 1): minutes(5)}) is None

    def test_matches_brute_force_for_five_stores(self) -> None:
        stores = [11, 12, 13, 14, 15]
        positions = {START: 0, 11: 3, 12: 9, 13: 4, 14: 15, 15: 7}
        legs = {
            (a, b): minutes(abs(positions[a] - positions[b]) + 1)
            for a in positions
            for b in stores
            if a != b
        }
        best = best_visit_order(stores, legs)
        assert best is not None

        brute_force = []
        for order in permutations(stores):
            route = walk(order, legs)
            assert route is not None
            brute_force.append(route.seconds)
        assert best.seconds == min(brute_force)


class TestProblems:
    def test_item_without_offers_is_reported(self) -> None:
        data = reference_input(60)
        result = find_plans(replace(data, basket=[*data.basket, BasketItem(999, 1)]))
        assert result.plans == []
        assert result.problem is PlanningProblem.ITEMS_UNAVAILABLE
        assert result.unavailable_product_ids == (999,)

    def test_store_limit_too_low(self) -> None:
        data = replace(reference_input(60), prices={A: {M1: 10000}, B: {M2: 18000}}, max_stores=1)
        result = find_plans(data)
        assert result.problem is PlanningProblem.STORE_LIMIT_TOO_LOW
        assert result.min_required_stores == 2

    def test_time_limit_too_low_reports_minimum(self) -> None:
        result = find_plans(reference_input(max_total_minutes=10))
        assert result.problem is PlanningProblem.TIME_LIMIT_TOO_LOW
        assert result.min_required_seconds == 18 * 60

    def test_unreachable_store_gives_route_problem(self) -> None:
        result = find_plans(replace(reference_input(60), legs={}))
        assert result.problem is PlanningProblem.ROUTE_UNAVAILABLE

    def test_no_baseline_means_no_savings(self) -> None:
        data = replace(reference_input(60), prices={A: {M1: 10000}, B: {M2: 18000}})
        result = find_plans(data)
        assert len(result.plans) == 1
        assert result.baseline is None
        assert savings_kopecks(result.plans[0], result.baseline) is None

    def test_at_most_three_distinct_plans(self) -> None:
        stores = [1, 2, 3, 4]
        prices = {A: {s: 1000 + s for s in stores}, B: {s: 2000 - s for s in stores}}
        legs = {(a, b): minutes(1) for a in [START, *stores] for b in stores if a != b}
        data = PlanningInput(
            basket=[BasketItem(A, 1), BasketItem(B, 1)],
            prices=prices,
            legs=legs,
            max_stores=5,
            max_total_seconds=180 * 60,
            shopping_time=ShoppingTimeModel(),
            store_formats={},
        )
        result = find_plans(data)
        assert len(result.plans) == 3
        assert len({plan.store_ids for plan in result.plans}) == 3
        assert [p.total_kopecks for p in result.plans] == sorted(
            p.total_kopecks for p in result.plans
        )


class TestAlternative:
    PRICES: ClassVar = {1: {10: 100, 20: 120, 30: 90, 40: 120}}

    def test_cheapest_other_store_of_the_route(self) -> None:
        assert cheapest_alternative(1, self.PRICES, stores={10, 20, 40}, chosen_store=10) == (
            20,
            120,
        )

    def test_store_outside_the_route_is_ignored(self) -> None:
        assert cheapest_alternative(1, self.PRICES, stores={10, 20}, chosen_store=20) == (10, 100)

    def test_no_other_store(self) -> None:
        assert cheapest_alternative(1, self.PRICES, stores={10}, chosen_store=10) is None
        assert cheapest_alternative(2, self.PRICES, stores={10, 20}, chosen_store=10) is None
