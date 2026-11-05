from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.catalog_import.publisher import ImportReport
from app.core.config import get_settings
from app.main import app
from app.models import Offer, Product, Store
from app.routing import GeoPoint, NoRouteError, RoutingError, WalkingMatrix, get_routing_provider
from app.routing.fake import FakeRoutingProvider
from app.routing.geo import haversine_meters
from app.schemas.planning import PlanRequest
from app.services.catalog import load_fresh_offers
from tests.api.plan_helpers import CARTS, ITMO, calculate, product_id_by_name


class TestSuccessfulPlans:
    def test_plans_respect_limits_and_ordering(
        self, client: TestClient, user_headers: dict[str, str], filled_cart: str
    ) -> None:
        response = calculate(client, user_headers, filled_cart)

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["data_is_synthetic"] is True
        assert 1 <= len(body["plans"]) <= 3

        keys = [(p["total_kopecks"], p["total_seconds"], p["stores_count"]) for p in body["plans"]]
        assert keys == sorted(keys)
        for plan in body["plans"]:
            assert plan["stores_count"] <= 3
            assert plan["total_seconds"] <= 120 * 60
            assert plan["total_seconds"] == plan["walking_seconds"] + plan["shopping_seconds"]
            assert plan["total_kopecks"] == sum(stop["subtotal_kopecks"] for stop in plan["stops"])
            bought = {
                item["product"]["id"]: item["quantity"]
                for s in plan["stops"]
                for item in s["items"]
            }
            assert sorted(bought.values()) == [1, 2, 3]
            assert [stop["position"] for stop in plan["stops"]] == list(
                range(1, plan["stores_count"] + 1)
            )

    def test_route_starts_at_user_and_is_marked_as_fake(
        self, client: TestClient, user_headers: dict[str, str], filled_cart: str
    ) -> None:
        plan = calculate(client, user_headers, filled_cart).json()["plans"][0]

        assert plan["route"]["provider"] == "fake"
        assert plan["route"]["uses_road_network"] is False
        assert plan["route"]["points"][0] == ITMO
        last_store = plan["stops"][-1]["store"]
        assert plan["route"]["points"][-1] == {
            "latitude": last_store["latitude"],
            "longitude": last_store["longitude"],
        }

    def test_savings_are_relative_to_best_single_store(
        self, client: TestClient, user_headers: dict[str, str], filled_cart: str
    ) -> None:
        body = calculate(client, user_headers, filled_cart, max_stores=5).json()
        baseline = body["baseline"]
        best = body["plans"][0]
        if baseline is None:
            assert best["savings_kopecks"] is None
        else:
            assert best["savings_kopecks"] == baseline["total_kopecks"] - best["total_kopecks"]

    def test_single_store_limit(
        self, client: TestClient, user_headers: dict[str, str], filled_cart: str
    ) -> None:
        body = calculate(client, user_headers, filled_cart, max_stores=1).json()
        assert body["status"] == "ok"
        assert all(plan["stores_count"] == 1 for plan in body["plans"])
        assert body["plans"][0]["savings_kopecks"] == 0

    def test_confirmed_substitution_replaces_product(
        self,
        client: TestClient,
        session: Session,
        user_headers: dict[str, str],
        filled_cart: str,
    ) -> None:
        milk = product_id_by_name(session, "Молоко 2,5%")
        kefir = product_id_by_name(session, "Кефир")
        body = calculate(
            client,
            user_headers,
            filled_cart,
            substitutions=[{"product_id": milk, "replacement_product_id": kefir}],
        ).json()

        bought = {
            item["product"]["id"] for stop in body["plans"][0]["stops"] for item in stop["items"]
        }
        assert kefir in bought
        assert milk not in bought


class TestProblems:
    def test_too_short_time_limit(
        self, client: TestClient, user_headers: dict[str, str], filled_cart: str
    ) -> None:
        body = calculate(client, user_headers, filled_cart, max_total_minutes=10).json()

        assert body["status"] == "no_plans"
        assert body["plans"] == []
        assert body["problem"]["reason"] == "time_limit_too_low"
        assert body["problem"]["min_required_minutes"] > 10

    def test_stale_prices_make_item_unavailable(
        self,
        client: TestClient,
        session: Session,
        user_headers: dict[str, str],
        filled_cart: str,
    ) -> None:
        milk = product_id_by_name(session, "Молоко 2,5%")
        session.execute(
            update(Offer)
            .where(Offer.product_id == milk)
            .values(source_updated_at=datetime.now(UTC) - timedelta(hours=30))
        )
        session.commit()

        body = calculate(client, user_headers, filled_cart).json()
        assert body["status"] == "no_plans"
        assert body["problem"]["reason"] == "items_unavailable"
        assert [p["id"] for p in body["problem"]["unavailable_products"]] == [milk]

    def test_empty_list(
        self, client: TestClient, user_headers: dict[str, str], demo_catalog: ImportReport
    ) -> None:
        cart_id = client.post(CARTS, headers=user_headers, json={"name": "Пусто"}).json()["id"]
        response = calculate(client, user_headers, cart_id)
        assert response.status_code == 422
        assert response.json()["code"] == "cart_empty"

    def test_other_users_list(
        self,
        client: TestClient,
        filled_cart: str,
        register: Callable[[str], dict[str, str]],
    ) -> None:
        assert calculate(client, register("mallory@example.com"), filled_cart).status_code == 404

    @pytest.mark.parametrize(
        "overrides",
        [
            {"max_stores": 0},
            {"max_stores": 6},
            {"max_total_minutes": 9},
            {"max_total_minutes": 181},
        ],
    )
    def test_invalid_limits(
        self,
        client: TestClient,
        user_headers: dict[str, str],
        filled_cart: str,
        overrides: dict[str, int],
    ) -> None:
        assert calculate(client, user_headers, filled_cart, **overrides).status_code == 422

    def test_routing_outage_returns_503(
        self, client: TestClient, user_headers: dict[str, str], filled_cart: str
    ) -> None:
        class BrokenRouting(FakeRoutingProvider):
            def walking_matrix(
                self, origins: Sequence[GeoPoint], destinations: Sequence[GeoPoint]
            ) -> WalkingMatrix:
                raise RoutingError("timeout")

        app.dependency_overrides[get_routing_provider] = BrokenRouting
        response = calculate(client, user_headers, filled_cart)
        assert response.status_code == 503
        assert response.json()["code"] == "routing_unavailable"

    def test_start_far_from_roads(
        self, client: TestClient, user_headers: dict[str, str], filled_cart: str
    ) -> None:
        class NoRoads(FakeRoutingProvider):
            def walking_matrix(
                self, origins: Sequence[GeoPoint], destinations: Sequence[GeoPoint]
            ) -> WalkingMatrix:
                raise NoRouteError("точка посреди Невы")

        app.dependency_overrides[get_routing_provider] = NoRoads
        body = calculate(client, user_headers, filled_cart).json()
        assert body["status"] == "no_plans"
        assert body["problem"]["reason"] == "route_unavailable"

    def test_catalog_not_loaded(
        self, client: TestClient, session: Session, user_headers: dict[str, str]
    ) -> None:
        session.add(
            Product(
                external_id="p1",
                name="Товар",
                category="Бакалея",
                package_amount=1,
                package_unit="pcs",
            )
        )
        session.commit()
        product_id = session.scalar(select(Product.id).where(Product.external_id == "p1"))
        cart_id = client.post(CARTS, headers=user_headers, json={"name": "Список"}).json()["id"]
        client.post(
            f"{CARTS}/{cart_id}/items", headers=user_headers, json={"product_id": product_id}
        )

        response = calculate(client, user_headers, cart_id)
        assert response.status_code == 503
        assert response.json()["code"] == "catalog_not_loaded"


class TestRadius:
    """Круг на карте: магазины дальше radius_meters от старта по прямой не рассматриваются."""

    def test_plans_use_only_stores_inside_the_circle(
        self, client: TestClient, user_headers: dict[str, str], filled_cart: str
    ) -> None:
        small = calculate(client, user_headers, filled_cart, radius_meters=100).json()
        radius = small["problem"]["min_required_radius_meters"]

        body = calculate(client, user_headers, filled_cart, radius_meters=radius).json()
        assert body["status"] == "ok"
        start = GeoPoint(ITMO["latitude"], ITMO["longitude"])
        for plan in body["plans"]:
            for stop in plan["stops"]:
                store = GeoPoint(stop["store"]["latitude"], stop["store"]["longitude"])
                assert haversine_meters(start, store) <= radius

    def test_too_small_radius_suggests_a_bigger_one(
        self, client: TestClient, user_headers: dict[str, str], filled_cart: str
    ) -> None:
        body = calculate(client, user_headers, filled_cart, radius_meters=100).json()

        assert body["status"] == "no_plans"
        assert body["problem"]["reason"] == "radius_too_small"
        assert len(body["problem"]["unavailable_products"]) == 3
        assert body["problem"]["min_required_radius_meters"] > 100

    def test_without_radius_nothing_changes(
        self, client: TestClient, user_headers: dict[str, str], filled_cart: str
    ) -> None:
        plain = calculate(client, user_headers, filled_cart).json()["plans"]
        wide = calculate(client, user_headers, filled_cart, radius_meters=5000).json()["plans"]
        assert [p["total_kopecks"] for p in plain] == [p["total_kopecks"] for p in wide]

    def test_items_missing_everywhere_are_not_blamed_on_radius(
        self,
        client: TestClient,
        session: Session,
        user_headers: dict[str, str],
        filled_cart: str,
    ) -> None:
        milk = product_id_by_name(session, "Молоко 2,5%")
        session.execute(update(Offer).where(Offer.product_id == milk).values(in_stock=False))
        session.commit()

        problem = calculate(client, user_headers, filled_cart, radius_meters=100).json()["problem"]
        assert problem["reason"] == "items_unavailable"
        assert problem["min_required_radius_meters"] is None

    @pytest.mark.parametrize("radius", [99, 5001])
    def test_radius_bounds(
        self, client: TestClient, user_headers: dict[str, str], filled_cart: str, radius: int
    ) -> None:
        response = calculate(client, user_headers, filled_cart, radius_meters=radius)
        assert response.status_code == 422


class TestFreshnessBoundary:
    """Граница 24 часов: ровно 24 часа ещё свежо, а 24 часа и 1 секунда уже нет."""

    @pytest.mark.parametrize(
        ("age", "expected"),
        [
            (timedelta(hours=23, minutes=59, seconds=59), True),
            (timedelta(hours=24), True),
            (timedelta(hours=24, seconds=1), False),
        ],
    )
    def test_offer_age(
        self, session: Session, demo_catalog: ImportReport, age: timedelta, expected: bool
    ) -> None:
        offer = session.scalar(select(Offer).where(Offer.in_stock.is_(True)).limit(1))
        assert offer is not None
        now = offer.source_updated_at + age

        fresh = load_fresh_offers(
            session,
            demo_catalog.import_id,
            [offer.product_id],
            now,
            get_settings().offer_max_age_hours,
        )
        assert (offer.id in {o.id for o in fresh}) is expected

    def test_unknown_availability_is_not_used(
        self, session: Session, demo_catalog: ImportReport
    ) -> None:
        offer = session.scalar(select(Offer).where(Offer.in_stock.is_(True)).limit(1))
        assert offer is not None
        offer.in_stock = None
        session.commit()

        fresh = load_fresh_offers(
            session, demo_catalog.import_id, [offer.product_id], datetime.now(UTC), 24
        )
        assert offer.id not in {o.id for o in fresh}

    def test_inactive_store_is_not_used(self, session: Session, demo_catalog: ImportReport) -> None:
        offer = session.scalar(select(Offer).where(Offer.in_stock.is_(True)).limit(1))
        assert offer is not None
        session.execute(update(Store).where(Store.id == offer.store_id).values(is_active=False))
        session.commit()

        fresh = load_fresh_offers(
            session, demo_catalog.import_id, [offer.product_id], datetime.now(UTC), 24
        )
        assert offer.store_id not in {o.store_id for o in fresh}


def test_plan_request_defaults() -> None:
    request = PlanRequest.model_validate({"start": ITMO})
    assert (request.max_stores, request.max_total_minutes) == (3, 60)
