from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from httpx2 import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.catalog_import.publisher import ImportReport
from app.models import Product
from tests.conftest import PASSWORD

CARTS = "/api/v1/carts"


@pytest.fixture
def product_ids(session: Session, demo_catalog: ImportReport) -> list[int]:
    return list(session.scalars(select(Product.id).order_by(Product.id).limit(31)))


@pytest.fixture
def cart_id(client: TestClient, user_headers: dict[str, str]) -> str:
    response = client.post(CARTS, headers=user_headers, json={"name": "На неделю"})
    assert response.status_code == 201
    return response.json()["id"]


def add(
    client: TestClient, headers: dict[str, str], cart_id: str, product_id: int, quantity: int
) -> Response:
    return client.post(
        f"{CARTS}/{cart_id}/items",
        headers=headers,
        json={"product_id": product_id, "quantity": quantity},
    )


class TestCartCrud:
    def test_create_get_rename_delete(
        self, client: TestClient, user_headers: dict[str, str], cart_id: str
    ) -> None:
        assert client.get(f"{CARTS}/{cart_id}", headers=user_headers).json()["items"] == []

        renamed = client.patch(
            f"{CARTS}/{cart_id}", headers=user_headers, json={"name": "Праздник"}
        )
        assert renamed.json()["name"] == "Праздник"

        summaries = client.get(CARTS, headers=user_headers).json()
        assert [(s["id"], s["items_count"]) for s in summaries] == [(cart_id, 0)]

        assert client.delete(f"{CARTS}/{cart_id}", headers=user_headers).status_code == 204
        assert client.get(f"{CARTS}/{cart_id}", headers=user_headers).status_code == 404

    def test_empty_name_is_rejected(self, client: TestClient, user_headers: dict[str, str]) -> None:
        assert client.post(CARTS, headers=user_headers, json={"name": ""}).status_code == 422


class TestStatus:
    def test_new_cart_is_active_and_status_can_change(
        self, client: TestClient, user_headers: dict[str, str], cart_id: str
    ) -> None:
        assert client.get(f"{CARTS}/{cart_id}", headers=user_headers).json()["status"] == "active"

        saved = client.patch(f"{CARTS}/{cart_id}", headers=user_headers, json={"status": "saved"})
        assert saved.status_code == 200
        assert (saved.json()["status"], saved.json()["name"]) == ("saved", "На неделю")

    def test_filter_by_status(
        self, client: TestClient, user_headers: dict[str, str], cart_id: str
    ) -> None:
        other = client.post(CARTS, headers=user_headers, json={"name": "Отложенная"}).json()["id"]
        client.patch(f"{CARTS}/{other}", headers=user_headers, json={"status": "saved"})

        saved = client.get(CARTS, headers=user_headers, params={"status": "saved"}).json()
        assert [cart["id"] for cart in saved] == [other]
        assert len(client.get(CARTS, headers=user_headers).json()) == 2

    @pytest.mark.parametrize("body", [{}, {"status": "lost"}, {"name": ""}])
    def test_invalid_update(
        self, client: TestClient, user_headers: dict[str, str], cart_id: str, body: dict
    ) -> None:
        response = client.patch(f"{CARTS}/{cart_id}", headers=user_headers, json=body)
        assert response.status_code == 422


class TestItems:
    def test_adding_same_product_sums_quantity(
        self, client: TestClient, user_headers: dict[str, str], cart_id: str, product_ids: list[int]
    ) -> None:
        add(client, user_headers, cart_id, product_ids[0], 2)
        response = add(client, user_headers, cart_id, product_ids[0], 3)

        items = response.json()["items"]
        assert len(items) == 1
        assert items[0]["quantity"] == 5
        assert items[0]["product"]["id"] == product_ids[0]

    @pytest.mark.parametrize(("quantity", "status"), [(0, 422), (1, 200), (99, 200), (100, 422)])
    def test_quantity_bounds(
        self,
        client: TestClient,
        user_headers: dict[str, str],
        cart_id: str,
        product_ids: list[int],
        quantity: int,
        status: int,
    ) -> None:
        assert add(client, user_headers, cart_id, product_ids[0], quantity).status_code == status

    def test_sum_above_99_is_rejected(
        self, client: TestClient, user_headers: dict[str, str], cart_id: str, product_ids: list[int]
    ) -> None:
        add(client, user_headers, cart_id, product_ids[0], 60)
        response = add(client, user_headers, cart_id, product_ids[0], 40)
        assert response.status_code == 422
        assert response.json()["code"] == "quantity_limit_exceeded"

    def test_thirty_items_allowed_thirty_first_rejected(
        self, client: TestClient, user_headers: dict[str, str], cart_id: str, product_ids: list[int]
    ) -> None:
        for product_id in product_ids[:30]:
            assert add(client, user_headers, cart_id, product_id, 1).status_code == 200
        response = add(client, user_headers, cart_id, product_ids[30], 1)
        assert response.status_code == 422
        assert response.json()["code"] == "items_limit_exceeded"

    def test_update_and_remove_item(
        self, client: TestClient, user_headers: dict[str, str], cart_id: str, product_ids: list[int]
    ) -> None:
        add(client, user_headers, cart_id, product_ids[0], 1)
        url = f"{CARTS}/{cart_id}/items/{product_ids[0]}"

        updated = client.patch(url, headers=user_headers, json={"quantity": 7})
        assert updated.json()["items"][0]["quantity"] == 7

        removed = client.delete(url, headers=user_headers)
        assert removed.json()["items"] == []
        assert client.delete(url, headers=user_headers).status_code == 404

    def test_unknown_product(
        self, client: TestClient, user_headers: dict[str, str], cart_id: str
    ) -> None:
        response = add(client, user_headers, cart_id, 999_999, 1)
        assert response.status_code == 404
        assert response.json()["code"] == "product_not_found"


class TestIsolation:
    """Два пользователя не видят и не меняют корзины друг друга (F01)."""

    def test_other_user_gets_404_everywhere(
        self,
        client: TestClient,
        user_headers: dict[str, str],
        cart_id: str,
        product_ids: list[int],
        register: Callable[[str], dict[str, str]],
    ) -> None:
        intruder = register("mallory@example.com")

        assert client.get(f"{CARTS}/{cart_id}", headers=intruder).status_code == 404
        assert (
            client.patch(f"{CARTS}/{cart_id}", headers=intruder, json={"name": "x"}).status_code
            == 404
        )
        assert client.delete(f"{CARTS}/{cart_id}", headers=intruder).status_code == 404
        assert add(client, intruder, cart_id, product_ids[0], 1).status_code == 404
        assert client.get(CARTS, headers=intruder).json() == []

        assert client.get(f"{CARTS}/{cart_id}", headers=user_headers).status_code == 200

    def test_carts_survive_new_login(
        self, client: TestClient, user_headers: dict[str, str], cart_id: str
    ) -> None:
        login = client.post(
            "/api/v1/auth/login", json={"email": "alice@example.com", "password": PASSWORD}
        )
        headers = {"Authorization": f"Bearer {login.json()['tokens']['access_token']}"}
        assert [item["id"] for item in client.get(CARTS, headers=headers).json()] == [cart_id]
