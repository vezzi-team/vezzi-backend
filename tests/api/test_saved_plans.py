"""Сохранённые планы: выбор, отметки в магазине, завершение и история (D01)."""

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models import Offer, Plan
from tests.api.plan_helpers import CARTS, PLANS, calculate


def plans_of(
    client: TestClient, headers: dict[str, str], cart_id: str, **overrides: object
) -> list[dict[str, Any]]:
    response = calculate(client, headers, cart_id, **overrides)
    assert response.status_code == 200, response.text
    plans = response.json()["plans"]
    assert plans
    return plans


def all_items(plan: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for stop in plan["stops"] for item in stop["items"]]


class TestCalculationIsSaved:
    def test_calculated_plan_can_be_opened_later(
        self, client: TestClient, user_headers: dict[str, str], filled_cart: str
    ) -> None:
        plans = plans_of(client, user_headers, filled_cart)

        assert [plan["rank"] for plan in plans] == list(range(1, len(plans) + 1))
        assert {(plan["status"], plan["cart_id"]) for plan in plans} == {("planned", filled_cart)}
        opened = client.get(f"{PLANS}/{plans[0]['id']}", headers=user_headers)
        assert opened.json() == plans[0]

    def test_new_calculation_replaces_unchosen_plans(
        self, client: TestClient, user_headers: dict[str, str], filled_cart: str
    ) -> None:
        first = plans_of(client, user_headers, filled_cart)
        second = plans_of(client, user_headers, filled_cart)

        assert client.get(f"{PLANS}/{first[0]['id']}", headers=user_headers).status_code == 404
        history = client.get(PLANS, headers=user_headers).json()
        assert {plan["id"] for plan in history} == {plan["id"] for plan in second}

    def test_plan_keeps_its_prices_when_catalog_changes(
        self, client: TestClient, session: Session, user_headers: dict[str, str], filled_cart: str
    ) -> None:
        plan = plans_of(client, user_headers, filled_cart)[0]
        session.execute(update(Offer).values(price_kopecks=Offer.price_kopecks + 10_000))
        session.commit()

        opened = client.get(f"{PLANS}/{plan['id']}", headers=user_headers).json()
        assert opened["total_kopecks"] == plan["total_kopecks"]

    def test_plan_keeps_price_conditions(
        self, client: TestClient, session: Session, user_headers: dict[str, str], filled_cart: str
    ) -> None:
        session.execute(
            update(Offer).values(
                card_price_kopecks=100, price_type="promo", price_conditions="акция"
            )
        )
        session.commit()

        item = all_items(plans_of(client, user_headers, filled_cart)[0])[0]
        assert (item["card_price_kopecks"], item["price_type"]) == (100, "promo")
        assert item["price_conditions"] == "акция"
        assert item["total_kopecks"] == item["unit_price_kopecks"] * item["quantity"]

    def test_alternative_is_another_store_of_the_same_route(
        self, client: TestClient, user_headers: dict[str, str], filled_cart: str
    ) -> None:
        for plan in plans_of(client, user_headers, filled_cart, max_stores=5):
            route_stores = {stop["store"]["id"] for stop in plan["stops"]}
            for stop in plan["stops"]:
                for item in stop["items"]:
                    assert item["status"] == "planned"
                    if item["alternative_store_id"] is None:
                        continue
                    assert item["alternative_store_id"] in route_stores - {stop["store"]["id"]}
                    # Товар назначен в самый дешёвый магазин маршрута, запасной не дешевле.
                    assert item["alternative_price_kopecks"] >= item["unit_price_kopecks"]


class TestShopping:
    def test_start_mark_and_complete(
        self, client: TestClient, user_headers: dict[str, str], filled_cart: str
    ) -> None:
        plans = plans_of(client, user_headers, filled_cart)
        chosen, others = plans[-1], plans[:-1]

        started = client.post(f"{PLANS}/{chosen['id']}/start", headers=user_headers).json()
        assert started["status"] == "active"
        assert started["started_at"] is not None
        for other in others:
            assert client.get(f"{PLANS}/{other['id']}", headers=user_headers).status_code == 404

        item_id = all_items(started)[0]["id"]
        marked = client.patch(
            f"{PLANS}/{chosen['id']}/items/{item_id}",
            headers=user_headers,
            json={"status": "bought"},
        ).json()
        assert [item["status"] for item in all_items(marked)].count("bought") == 1

        done = client.post(f"{PLANS}/{chosen['id']}/complete", headers=user_headers).json()
        assert done["status"] == "completed"
        assert client.get(f"{CARTS}/{filled_cart}", headers=user_headers).json()["status"] == (
            "completed"
        )

        history = client.get(PLANS, headers=user_headers, params={"status": "completed"}).json()
        assert [(h["id"], h["items_count"], h["bought_count"]) for h in history] == [
            (chosen["id"], 3, 1)
        ]

    def test_plan_cannot_be_started_twice(
        self, client: TestClient, user_headers: dict[str, str], filled_cart: str
    ) -> None:
        plan_id = plans_of(client, user_headers, filled_cart)[0]["id"]
        assert client.post(f"{PLANS}/{plan_id}/start", headers=user_headers).status_code == 200

        again = client.post(f"{PLANS}/{plan_id}/start", headers=user_headers)
        assert again.status_code == 409
        assert again.json()["code"] == "plan_already_started"

    def test_one_active_plan_per_cart(
        self, client: TestClient, user_headers: dict[str, str], filled_cart: str
    ) -> None:
        first = plans_of(client, user_headers, filled_cart)[0]["id"]
        client.post(f"{PLANS}/{first}/start", headers=user_headers)
        second = plans_of(client, user_headers, filled_cart)[0]["id"]

        response = client.post(f"{PLANS}/{second}/start", headers=user_headers)
        assert response.status_code == 409
        assert response.json()["code"] == "active_plan_exists"
        assert client.get(f"{PLANS}/{first}", headers=user_headers).json()["status"] == "active"

    def test_plan_with_stale_prices_cannot_be_started(
        self, client: TestClient, session: Session, user_headers: dict[str, str], filled_cart: str
    ) -> None:
        plan_id = plans_of(client, user_headers, filled_cart)[0]["id"]
        session.execute(
            update(Plan)
            .where(Plan.id == uuid.UUID(plan_id))
            .values(created_at=datetime.now(UTC) - timedelta(hours=25))
        )
        session.commit()

        response = client.post(f"{PLANS}/{plan_id}/start", headers=user_headers)
        assert response.status_code == 409
        assert response.json()["code"] == "plan_expired"

    def test_marks_and_completion_need_a_started_plan(
        self, client: TestClient, user_headers: dict[str, str], filled_cart: str
    ) -> None:
        plan = plans_of(client, user_headers, filled_cart)[0]
        item_id = all_items(plan)[0]["id"]

        mark = client.patch(
            f"{PLANS}/{plan['id']}/items/{item_id}", headers=user_headers, json={"status": "bought"}
        )
        complete = client.post(f"{PLANS}/{plan['id']}/complete", headers=user_headers)
        assert (mark.status_code, mark.json()["code"]) == (409, "plan_not_active")
        assert (complete.status_code, complete.json()["code"]) == (409, "plan_not_active")

    def test_unknown_item_and_bad_status(
        self, client: TestClient, user_headers: dict[str, str], filled_cart: str
    ) -> None:
        plan = plans_of(client, user_headers, filled_cart)[0]
        client.post(f"{PLANS}/{plan['id']}/start", headers=user_headers)
        items_url = f"{PLANS}/{plan['id']}/items"

        unknown = client.patch(
            f"{items_url}/999999", headers=user_headers, json={"status": "bought"}
        )
        assert (unknown.status_code, unknown.json()["code"]) == (404, "plan_item_not_found")
        item_id = all_items(plan)[0]["id"]
        bad = client.patch(f"{items_url}/{item_id}", headers=user_headers, json={"status": "eaten"})
        assert bad.status_code == 422


class TestOwnershipAndDeletion:
    def test_other_user_gets_404_everywhere(
        self,
        client: TestClient,
        user_headers: dict[str, str],
        filled_cart: str,
        register: Callable[[str], dict[str, str]],
    ) -> None:
        plan = plans_of(client, user_headers, filled_cart)[0]
        url = f"{PLANS}/{plan['id']}"
        item_url = f"{url}/items/{all_items(plan)[0]['id']}"
        intruder = register("mallory@example.com")

        assert client.get(url, headers=intruder).status_code == 404
        assert client.post(f"{url}/start", headers=intruder).status_code == 404
        assert (
            client.patch(item_url, headers=intruder, json={"status": "bought"}).status_code == 404
        )
        assert client.post(f"{url}/complete", headers=intruder).status_code == 404
        assert client.delete(url, headers=intruder).status_code == 404
        assert client.get(PLANS, headers=intruder).json() == []
        assert client.get(url, headers=user_headers).status_code == 200

    def test_deleting_cart_keeps_plan_in_history(
        self, client: TestClient, user_headers: dict[str, str], filled_cart: str
    ) -> None:
        plan_id = plans_of(client, user_headers, filled_cart)[0]["id"]
        client.post(f"{PLANS}/{plan_id}/start", headers=user_headers)

        assert client.delete(f"{CARTS}/{filled_cart}", headers=user_headers).status_code == 204
        opened = client.get(f"{PLANS}/{plan_id}", headers=user_headers).json()
        assert (opened["status"], opened["cart_id"]) == ("active", None)

    def test_delete_plan(
        self, client: TestClient, user_headers: dict[str, str], filled_cart: str
    ) -> None:
        plan_id = plans_of(client, user_headers, filled_cart)[0]["id"]
        assert client.delete(f"{PLANS}/{plan_id}", headers=user_headers).status_code == 204
        assert client.get(f"{PLANS}/{plan_id}", headers=user_headers).status_code == 404

    def test_deleting_account_removes_plans(
        self, client: TestClient, session: Session, user_headers: dict[str, str], filled_cart: str
    ) -> None:
        plans_of(client, user_headers, filled_cart)
        assert client.delete("/api/v1/users/me", headers=user_headers).status_code == 204
        assert session.scalar(select(func.count()).select_from(Plan)) == 0
