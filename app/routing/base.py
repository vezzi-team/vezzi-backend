"""Общий интерфейс провайдеров пешеходных маршрутов.

Расчёт планов работает только с этим интерфейсом, поэтому движок маршрутов можно
заменить, не меняя алгоритм. Сейчас это OSRM и тестовая заглушка (ROUTING_PROVIDER).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class GeoPoint:
    latitude: float
    longitude: float


@dataclass(frozen=True)
class WalkingMatrix:
    """seconds[i][j] и meters[i][j]: путь от origins[i] до destinations[j]; None, если пути нет."""

    seconds: list[list[int | None]]
    meters: list[list[int | None]]


@dataclass(frozen=True)
class WalkingRoute:
    points: list[GeoPoint]
    seconds: int
    meters: int


class RoutingError(Exception):
    """Провайдер недоступен или ответил ошибкой."""


class NoRouteError(RoutingError):
    """Провайдер работает, но пешего пути между точками нет."""


class RoutingProvider(Protocol):
    name: str
    uses_road_network: bool

    def walking_matrix(
        self, origins: Sequence[GeoPoint], destinations: Sequence[GeoPoint]
    ) -> WalkingMatrix: ...

    def walking_route(self, waypoints: Sequence[GeoPoint]) -> WalkingRoute: ...
