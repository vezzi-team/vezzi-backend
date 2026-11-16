"""Аналоги для замены товара (F10): GET /products/{id}/analogs."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.catalog_import.publisher import publish_catalog
from app.catalog_import.records import OfferRecord, ParsedCatalog, ProductRecord, StoreRecord
from app.models import PackageUnit, Product, StoreFormat
from tests.api.plan_helpers import product_id_by_name

NOW = datetime.now(UTC)

# (бренд, название, вид, фасовка в мл, цены в двух магазинах; None значит, что цены нет)
MILK_SHELF = [
    ("Простоквашино", "Молоко пастеризованное 2,5%, 930 мл", "Молоко", 930, (9990, 10490)),
    ("Домик в деревне", "Молоко пастеризованное 2,5%, 950 мл", "Молоко (доп.)", 950, (9490, 8990)),
    ("Экомилк", "Молоко пастеризованное 2,5%, 900 мл", "Молоко", 900, (8490, None)),
    ("Савушкин", "Молоко пастеризованное 2,5%, 1 л", "Молоко", 1000, (None, 10990)),
    ("Кубанская бурёнка", "Молоко пастеризованное 2,5%, 930 мл", "Молоко", 930, (9290, 9390)),
    ("Домик в деревне", "Молоко пастеризованное 3,2%, 950 мл", "Молоко", 950, (9990, 9990)),
    ("Красная цена", "Молоко пастеризованное 2,5%, 1,4 л", "Молоко", 1400, (11990, 11990)),
    ("Простоквашино", "Кефир 2,5%, 930 мл", "Кефир", 930, (8990, 8990)),
    ("Вкуснотеево", "Молоко пастеризованное 2,5%, 900 мл", "Молоко", 900, (7990, 7990)),
]
STALE_BRAND = "Вкуснотеево"  # у этого молока цены только устаревшие


@pytest.fixture
def milk_catalog(session: Session) -> None:
    catalog = ParsedCatalog(is_synthetic=True)
    for store in ("s1", "s2"):
        catalog.stores.append(
            StoreRecord(
                external_id=store,
                chain="Сеть",
                name=f"Магазин {store}",
                address="Кронверкский пр., 49",
                latitude=59.957,
                longitude=30.308,
                format=StoreFormat.SUPERMARKET,
                is_active=True,
            )
        )
    for number, (brand, title, kind, amount, prices) in enumerate(MILK_SHELF, start=1):
        catalog.products.append(
            ProductRecord(
                external_id=f"p{number}",
                name=f"{brand} {title}",
                brand=brand,
                category="Молочные продукты",
                product_type=kind,
                package_amount=Decimal(amount),
                package_unit=PackageUnit.MILLILITER,
                attributes={},
            )
        )
        age = timedelta(days=30) if brand == STALE_BRAND else timedelta(hours=1)
        for store, price in zip(("s1", "s2"), prices, strict=True):
            if price is None:
                continue
            catalog.offers.append(
                OfferRecord(
                    row=len(catalog.offers) + 2,
                    store_external_id=store,
                    product_external_id=f"p{number}",
                    price_kopecks=price,
                    card_price_kopecks=None,
                    in_stock=True,
                    source_updated_at=NOW - age,
                    price_type="regular",
                    price_conditions=None,
                    source_product_id=None,
                    source_url=None,
                )
            )
    publish_catalog(session, catalog, source_name="milk", file_sha256="milk", now=NOW)


def analogs_of(client: TestClient, headers: dict[str, str], product_id: int) -> list[dict]:
    response = client.get(f"/api/v1/products/{product_id}/analogs", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


class TestAnalogs:
    def test_only_allowed_analogs_most_similar_first(
        self, client: TestClient, session: Session, user_headers: dict[str, str], milk_catalog: None
    ) -> None:
        milk = product_id_by_name(session, "Простоквашино Молоко")

        analogs = analogs_of(client, user_headers, milk)

        assert len(analogs) == 3
        allowed = {"Домик в деревне", "Экомилк", "Савушкин", "Кубанская бурёнка"}
        assert all(analog["brand"] in allowed for analog in analogs)
        assert all("2,5%" in analog["name"] for analog in analogs)
        similarities = [analog["similarity"] for analog in analogs]
        assert similarities == sorted(similarities, reverse=True)

    def test_price_is_the_cheapest_usable_one(
        self, client: TestClient, session: Session, user_headers: dict[str, str], milk_catalog: None
    ) -> None:
        cheapest = {"Домик в деревне": 8990, "Экомилк": 8490, "Савушкин": 10990}
        cheapest["Кубанская бурёнка"] = 9290

        analogs = analogs_of(
            client, user_headers, product_id_by_name(session, "Простоквашино Молоко")
        )

        assert all(analog["min_price_kopecks"] == cheapest[analog["brand"]] for analog in analogs)

    def test_product_with_only_stale_prices_is_not_offered(
        self, client: TestClient, session: Session, user_headers: dict[str, str], milk_catalog: None
    ) -> None:
        for brand, title, *_ in MILK_SHELF[:5]:
            milk = product_id_by_name(session, f"{brand} {title}")
            assert not any(
                a["brand"] == STALE_BRAND for a in analogs_of(client, user_headers, milk)
            )

    def test_no_allowed_analog_is_an_empty_list(
        self, client: TestClient, session: Session, user_headers: dict[str, str], milk_catalog: None
    ) -> None:
        kefir = product_id_by_name(session, "Кефир")
        assert analogs_of(client, user_headers, kefir) == []

    @pytest.mark.parametrize("catalog_loaded", [True, False])
    def test_product_not_sold_now_has_no_analogs(
        self,
        client: TestClient,
        session: Session,
        user_headers: dict[str, str],
        catalog_loaded: bool,
        request: pytest.FixtureRequest,
    ) -> None:
        if catalog_loaded:
            request.getfixturevalue("milk_catalog")
        old_milk = Product(
            external_id="old-milk",
            name="Молоко из прошлой загрузки 2,5%, 930 мл",
            category="Молочные продукты",
            product_type="Молоко",
            package_amount=Decimal(930),
            package_unit=PackageUnit.MILLILITER,
        )
        session.add(old_milk)
        session.commit()

        assert analogs_of(client, user_headers, old_milk.id) == []

    def test_unknown_product(self, client: TestClient, user_headers: dict[str, str]) -> None:
        response = client.get("/api/v1/products/123456/analogs", headers=user_headers)
        assert response.status_code == 404

    def test_requires_auth(self, client: TestClient) -> None:
        assert client.get("/api/v1/products/1/analogs").status_code == 401
