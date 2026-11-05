import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.catalog_import.publisher import ImportReport
from tests.api.plan_helpers import CARTS, product_id_by_name


@pytest.fixture
def filled_cart(
    client: TestClient, session: Session, user_headers: dict[str, str], demo_catalog: ImportReport
) -> str:
    """Корзина «Ужин» из трёх товаров демо-каталога."""
    cart_id = client.post(CARTS, headers=user_headers, json={"name": "Ужин"}).json()["id"]
    for fragment, quantity in [("Молоко 2,5%", 2), ("Хлеб Бородинский", 1), ("Спагетти", 3)]:
        response = client.post(
            f"{CARTS}/{cart_id}/items",
            headers=user_headers,
            json={"product_id": product_id_by_name(session, fragment), "quantity": quantity},
        )
        assert response.status_code == 200
    return cart_id
