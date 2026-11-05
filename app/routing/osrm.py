"""OSRM: открытый маршрутизатор на картах OpenStreetMap, развёрнутый на нашем сервере.

Документация API: https://project-osrm.org/docs/v5.24.0/api/
Внимание: OSRM принимает и возвращает координаты в порядке «долгота, широта».
"""

from collections.abc import Sequence
from typing import Any

import httpx2

from app.routing.base import GeoPoint, NoRouteError, RoutingError, WalkingMatrix, WalkingRoute

# Если точка дальше этого расстояния от ближайшей пешеходной дороги, считаем её недостижимой.
MAX_SNAP_DISTANCE_METERS = 300


class OsrmRoutingProvider:
    name = "osrm"
    uses_road_network = True

    def __init__(self, base_url: str, timeout: float, client: httpx2.Client | None = None) -> None:
        self._client = client or httpx2.Client(base_url=base_url, timeout=timeout)

    def walking_matrix(
        self, origins: Sequence[GeoPoint], destinations: Sequence[GeoPoint]
    ) -> WalkingMatrix:
        points = [*origins, *destinations]
        params = {
            "sources": ";".join(str(i) for i in range(len(origins))),
            "destinations": ";".join(str(i) for i in range(len(origins), len(points))),
            "annotations": "duration,distance",
        }
        data = self._get(f"/table/v1/foot/{_coordinates(points)}", params)
        _check_snapping(data.get("sources", []) + data.get("destinations", []))
        return WalkingMatrix(
            seconds=_round_matrix(data["durations"]), meters=_round_matrix(data["distances"])
        )

    def walking_route(self, waypoints: Sequence[GeoPoint]) -> WalkingRoute:
        params = {"overview": "full", "geometries": "geojson", "steps": "false"}
        data = self._get(f"/route/v1/foot/{_coordinates(waypoints)}", params)
        _check_snapping(data.get("waypoints", []))
        route = data["routes"][0]
        return WalkingRoute(
            points=[
                GeoPoint(latitude=lat, longitude=lon)
                for lon, lat in route["geometry"]["coordinates"]
            ],
            seconds=round(route["duration"]),
            meters=round(route["distance"]),
        )

    def _get(self, path: str, params: dict[str, str]) -> dict[str, Any]:
        try:
            response = self._client.get(path, params=params)
            data: dict[str, Any] = response.json()
        except (httpx2.HTTPError, ValueError) as exc:
            raise RoutingError("OSRM недоступен") from exc

        code = data.get("code")
        if code in {"NoRoute", "NoSegment"}:
            raise NoRouteError(f"OSRM: {code}")
        if response.status_code != 200 or code != "Ok":
            raise RoutingError(f"OSRM вернул ошибку: {code or response.status_code}")
        return data


def _coordinates(points: Sequence[GeoPoint]) -> str:
    return ";".join(f"{p.longitude:.6f},{p.latitude:.6f}" for p in points)


def _round_matrix(rows: list[list[float | None]]) -> list[list[int | None]]:
    return [[None if value is None else round(value) for value in row] for row in rows]


def _check_snapping(waypoints: list[dict[str, Any]]) -> None:
    if any(point.get("distance", 0) > MAX_SNAP_DISTANCE_METERS for point in waypoints):
        raise NoRouteError("Точка слишком далеко от пешеходных дорог")
