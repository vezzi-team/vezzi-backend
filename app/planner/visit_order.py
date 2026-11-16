"""Порядок обхода магазинов (F09).

По ТЗ маршрут начинается в стартовой точке и заканчивается в последнем магазине.
Если пользователь попросил вернуться к старту, к маршруту добавляется путь от
последнего магазина обратно, и самый быстрый порядок выбирается уже с ним.
Магазинов не больше пяти, значит вариантов порядка не больше 5! = 120,
их можно честно перебрать все и взять самый быстрый.
"""

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from itertools import permutations

from app.planner.models import START, Leg, Place, TravelLegs


@dataclass(frozen=True)
class VisitRoute:
    store_order: tuple[int, ...]
    legs: tuple[Leg, ...]
    # Путь от последнего магазина обратно к старту; None, если возвращаться не нужно.
    return_leg: Leg | None = None

    @property
    def all_legs(self) -> tuple[Leg, ...]:
        return self.legs if self.return_leg is None else (*self.legs, self.return_leg)

    @property
    def seconds(self) -> int:
        return sum(leg.seconds for leg in self.all_legs)

    @property
    def meters(self) -> int:
        return sum(leg.meters for leg in self.all_legs)


def walk(
    store_order: Sequence[int], legs: TravelLegs, return_to_start: bool = False
) -> VisitRoute | None:
    """Маршрут по заданному порядку или None, если какой-то переход невозможен."""
    route_legs = []
    previous: Place = START
    for store_id in store_order:
        leg = legs.get((previous, store_id))
        if leg is None:
            return None
        route_legs.append(leg)
        previous = store_id
    if not return_to_start:
        return VisitRoute(tuple(store_order), tuple(route_legs))
    return_leg = legs.get((previous, START))
    if return_leg is None:
        return None
    return VisitRoute(tuple(store_order), tuple(route_legs), return_leg)


def best_visit_order(
    stores: Collection[int], legs: TravelLegs, return_to_start: bool = False
) -> VisitRoute | None:
    """Самый быстрый порядок обхода. При равном времени выбираем более короткий по метрам.

    permutations() от отсортированного списка выдаёт порядки по возрастанию,
    а строгое «<» оставляет первый из равных, так что результат детерминирован.
    """
    best: VisitRoute | None = None
    for order in permutations(sorted(stores)):
        route = walk(order, legs, return_to_start)
        if route is None:
            continue
        if best is None or (route.seconds, route.meters) < (best.seconds, best.meters):
            best = route
    return best
