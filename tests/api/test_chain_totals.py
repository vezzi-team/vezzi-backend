"""GET /carts/{id}/chain-totals на демо-каталоге, где ровно три сети."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.catalog_import.publisher import ImportReport
from app.models import Offer
from tests.api.plan_helpers import CARTS, product_id_by_name

DEMO_CHAINS = {"Демо-маркет", "Демо-экспресс", "Демо-гипер"}


def chain_totals(client: TestClient, headers: dict[str, str], cart_id: str, **params: object):
    return client.get(f"{CARTS}/{cart_id}/chain-totals", headers=headers, params=params)


def test_line_and_chain_totals(
    client: TestClient, user_headers: dict[str, str], filled_cart: str
) -> None:
    body = chain_totals(client, user_headers, filled_cart).json()

    assert {chain["chain"] for chain in body["chains"]} == DEMO_CHAINS
    assert body["data_is_synthetic"] is True
    for chain in body["chains"]:
        assert [line["quantity"] for line in chain["lines"]] == [2, 1, 3]  # порядок корзины
        counted = [line for line in chain["lines"] if line["status"] == "available"]
        for line in counted:
            assert line["total_kopecks"] == line["unit_price_kopecks"] * line["quantity"]
            assert line["store"]["chain"] == chain["chain"]
            assert line["is_fresh"] is True
            assert line["price_updated_at"].endswith("Z")
        assert chain["found_total_kopecks"] == sum(line["total_kopecks"] for line in counted)
        assert chain["found_items_count"] == len(counted)
        assert chain["items_count"] == 3
        assert chain["total_kopecks"] == (
            chain["found_total_kopecks"] if chain["is_complete"] else None
        )

    complete = [chain["total_kopecks"] for chain in body["chains"] if chain["is_complete"]]
    assert complete == sorted(complete)


def test_repeated_calculation_is_identical(
    client: TestClient, user_headers: dict[str, str], filled_cart: str
) -> None:
    first = chain_totals(client, user_headers, filled_cart).json()
    second = chain_totals(client, user_headers, filled_cart).json()
    assert first["chains"] == second["chains"]


def test_chain_filter(client: TestClient, user_headers: dict[str, str], filled_cart: str) -> None:
    body = chain_totals(
        client, user_headers, filled_cart, chain=["Демо-гипер", "Демо-маркет"]
    ).json()
    assert {chain["chain"] for chain in body["chains"]} == {"Демо-гипер", "Демо-маркет"}

    unknown = chain_totals(client, user_headers, filled_cart, chain=["Пятёрочка"])
    assert (unknown.status_code, unknown.json()["code"]) == (422, "unknown_chain")


def test_stale_price_makes_basket_incomplete(
    client: TestClient, session: Session, user_headers: dict[str, str], filled_cart: str
) -> None:
    milk = product_id_by_name(session, "Молоко 2,5%")
    session.execute(
        update(Offer)
        .where(Offer.product_id == milk)
        .values(source_updated_at=datetime.now(UTC) - timedelta(hours=30))
    )
    session.commit()

    for chain in chain_totals(client, user_headers, filled_cart).json()["chains"]:
        assert chain["is_complete"] is False
        assert chain["total_kopecks"] is None
        assert chain["coverage_percent"] < 100
        assert milk in {product["id"] for product in chain["missing_products"]}

        line = next(line for line in chain["lines"] if line["product"]["id"] == milk)
        if line["status"] != "not_sold":
            assert (line["status"], line["is_fresh"], line["total_kopecks"]) == (
                "stale",
                False,
                None,
            )
            assert line["unit_price_kopecks"] > 0  # цена видна, но в сумму не вошла


def test_card_price_and_conditions_reach_the_client(
    client: TestClient, session: Session, user_headers: dict[str, str], filled_cart: str
) -> None:
    milk = product_id_by_name(session, "Молоко 2,5%")
    session.execute(
        update(Offer)
        .where(Offer.product_id == milk)
        .values(card_price_kopecks=100, price_type="promo", price_conditions="до 10.11")
    )
    session.commit()

    for chain in chain_totals(client, user_headers, filled_cart).json()["chains"]:
        line = next(line for line in chain["lines"] if line["product"]["id"] == milk)
        if line["status"] == "available":
            assert line["card_price_kopecks"] == 100
            assert (line["price_type"], line["price_conditions"]) == ("promo", "до 10.11")
            assert line["total_kopecks"] == line["unit_price_kopecks"] * line["quantity"]

    card = client.get(f"/api/v1/products/{milk}", headers=user_headers).json()["offers"][0]
    assert (card["card_price_kopecks"], card["price_conditions"]) == (100, "до 10.11")


def test_empty_and_foreign_cart(
    client: TestClient,
    user_headers: dict[str, str],
    filled_cart: str,
    demo_catalog: ImportReport,
    register: Callable[[str], dict[str, str]],
) -> None:
    empty = client.post(CARTS, headers=user_headers, json={"name": "Пусто"}).json()["id"]
    response = chain_totals(client, user_headers, empty)
    assert (response.status_code, response.json()["code"]) == (422, "cart_empty")

    assert chain_totals(client, register("mallory@example.com"), filled_cart).status_code == 404
