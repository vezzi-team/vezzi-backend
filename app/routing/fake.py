"""Оценка пешего пути по прямой. Только для тестов и локальной разработки.

Прямая линия не является настоящим маршрутом (это прямо запрещает F09), поэтому
провайдер помечен uses_road_network = False, а в production запрещён настройками.
"""

from collections.abc import Sequence
from itertools import pairwise

from app.routing.base import GeoPoint, WalkingMatrix, WalkingRoute
from app.routing.geo import haversine_meters

WALKING_SPEED_METERS_PER_SECOND = 5000 / 3600
DETOUR_FACTOR = 1.3


class FakeRoutingProvider:
    name = "fake"
    uses_road_network = False

    def walking_matrix(
        self, origins: Sequence[GeoPoint], destinations: Sequence[GeoPoint]
    ) -> WalkingMatrix:
        meters: list[list[int | None]] = []
        seconds: list[list[int | None]] = []
        for origin in origins:
            distances = [self._distance(origin, destination) for destination in destinations]
            meters.append([round(d) for d in distances])
            seconds.append([round(d / WALKING_SPEED_METERS_PER_SECOND) for d in distances])
        return WalkingMatrix(seconds=seconds, meters=meters)

    def walking_route(self, waypoints: Sequence[GeoPoint]) -> WalkingRoute:
        meters = sum(self._distance(a, b) for a, b in pairwise(waypoints))
        return WalkingRoute(
            points=list(waypoints),
            seconds=round(meters / WALKING_SPEED_METERS_PER_SECOND),
            meters=round(meters),
        )

    @staticmethod
    def _distance(a: GeoPoint, b: GeoPoint) -> float:
        return haversine_meters(a, b) * DETOUR_FACTOR
