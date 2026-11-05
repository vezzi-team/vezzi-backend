"""Общие помощники тестов расчёта и сохранённых планов."""

from fastapi.testclient import TestClient
from httpx2 import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Product

CARTS = "/api/v1/carts"
PLANS = "/api/v1/plans"
ITMO = {"latitude": 59.9571, "longitude": 30.3084}


def product_id_by_name(session: Session, fragment: str) -> int:
    product_id = session.scalar(
        select(Product.id).where(Product.name.contains(fragment)).order_by(Product.id).limit(1)
    )
    assert product_id is not None
    return product_id


def calculate(
    client: TestClient, headers: dict[str, str], cart_id: str, **overrides: object
) -> Response:
    body = {"start": ITMO, "max_stores": 3, "max_total_minutes": 120, **overrides}
    return client.post(f"{CARTS}/{cart_id}/plans", headers=headers, json=body)
