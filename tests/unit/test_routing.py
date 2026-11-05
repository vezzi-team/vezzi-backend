import json
from collections.abc import Callable
from typing import Any

import httpx2
import pytest

from app.routing import GeoPoint, NoRouteError, RoutingError
from app.routing.fake import FakeRoutingProvider
from app.routing.osrm import OsrmRoutingProvider

START = GeoPoint(59.9571, 30.3084)
STORE = GeoPoint(59.9561, 30.3189)

type Handler = Callable[[httpx2.Request], httpx2.Response]


def json_response(payload: dict[str, Any], status: int = 200) -> httpx2.Response:
    return httpx2.Response(
        status, content=json.dumps(payload), headers={"content-type": "application/json"}
    )


def osrm(handler: Handler) -> OsrmRoutingProvider:
    client = httpx2.Client(base_url="http://osrm", transport=httpx2.MockTransport(handler))
    return OsrmRoutingProvider("http://osrm", 5, client=client)


class TestOsrm:
    def test_matrix_request_uses_lon_lat_order(self) -> None:
        seen: list[httpx2.Request] = []

        def handler(request: httpx2.Request) -> httpx2.Response:
            seen.append(request)
            return json_response(
                {
                    "code": "Ok",
                    "durations": [[671.6]],
                    "distances": [[930.4]],
                    "sources": [],
                    "destinations": [],
                }
            )

        matrix = osrm(handler).walking_matrix([START], [STORE])

        assert matrix.seconds == [[672]]
        assert matrix.meters == [[930]]
        assert "/table/v1/foot/30.308400,59.957100;30.318900,59.956100" in seen[0].url.path
        assert seen[0].url.params["sources"] == "0"
        assert seen[0].url.params["destinations"] == "1"

    def test_unreachable_cell_is_none(self) -> None:
        provider = osrm(
            lambda _: json_response({"code": "Ok", "durations": [[None]], "distances": [[None]]})
        )
        assert provider.walking_matrix([START], [STORE]).seconds == [[None]]

    def test_route_geometry_is_converted_to_lat_lon(self) -> None:
        payload = {
            "code": "Ok",
            "routes": [
                {
                    "duration": 671.6,
                    "distance": 930.4,
                    "geometry": {"coordinates": [[30.3084, 59.9571], [30.3189, 59.9561]]},
                }
            ],
            "waypoints": [{"distance": 3.2}, {"distance": 12.0}],
        }
        route = osrm(lambda _: json_response(payload)).walking_route([START, STORE])

        assert route.points == [START, STORE]
        assert (route.seconds, route.meters) == (672, 930)

    @pytest.mark.parametrize("code", ["NoRoute", "NoSegment"])
    def test_no_route(self, code: str) -> None:
        provider = osrm(lambda _: json_response({"code": code}, status=400))
        with pytest.raises(NoRouteError):
            provider.walking_route([START, STORE])

    def test_point_far_from_roads(self) -> None:
        payload = {
            "code": "Ok",
            "durations": [[1]],
            "distances": [[1]],
            "sources": [{"distance": 900}],
        }
        with pytest.raises(NoRouteError):
            osrm(lambda _: json_response(payload)).walking_matrix([START], [STORE])

    def test_server_error_and_timeout(self) -> None:
        with pytest.raises(RoutingError):
            osrm(lambda _: httpx2.Response(502, text="Bad Gateway")).walking_route([START, STORE])

        def timeout(request: httpx2.Request) -> httpx2.Response:
            raise httpx2.ConnectTimeout("timeout", request=request)

        with pytest.raises(RoutingError):
            osrm(timeout).walking_route([START, STORE])


class TestFake:
    def test_estimate_is_longer_than_straight_line(self) -> None:
        matrix = FakeRoutingProvider().walking_matrix([START], [STORE])
        meters = matrix.meters[0][0]
        assert meters is not None
        assert 700 < meters < 900

    def test_route_is_straight_lines(self) -> None:
        provider = FakeRoutingProvider()
        assert provider.uses_road_network is False
        assert provider.walking_route([START, STORE]).points == [START, STORE]
