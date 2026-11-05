"""Порядок обхода магазинов (F09).

Маршрут начинается в стартовой точке и заканчивается в последнем магазине,
домой не возвращаемся. Магазинов не больше пяти, значит вариантов порядка
не больше 5! = 120, их можно честно перебрать все и взять самый быстрый.
"""

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from itertools import permutations

from app.planner.models import START, Leg, Place, TravelLegs


@dataclass(frozen=True)
class VisitRoute:
    store_order: tuple[int, ...]
    legs: tuple[Leg, ...]

    @property
    def seconds(self) -> int:
        return sum(leg.seconds for leg in self.legs)

    @property
    def meters(self) -> int:
        return sum(leg.meters for leg in self.legs)


def walk(store_order: Sequence[int], legs: TravelLegs) -> VisitRoute | None:
    """Маршрут по заданному порядку или None, если какой-то переход невозможен."""
    route_legs = []
    previous: Place = START
    for store_id in store_order:
        leg = legs.get((previous, store_id))
        if leg is None:
            return None
        route_legs.append(leg)
        previous = store_id
    return VisitRoute(tuple(store_order), tuple(route_legs))


def best_visit_order(stores: Collection[int], legs: TravelLegs) -> VisitRoute | None:
    """Самый быстрый порядок обхода. При равном времени выбираем более короткий по метрам.

    permutations() от отсортированного списка выдаёт порядки по возрастанию,
    а строгое «<» оставляет первый из равных, так что результат детерминирован.
    """
    best: VisitRoute | None = None
    for order in permutations(sorted(stores)):
        route = walk(order, legs)
        if route is None:
            continue
        if best is None or (route.seconds, route.meters) < (best.seconds, best.meters):
            best = route
    return best
