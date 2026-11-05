from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.catalog_import.publisher import ImportReport, publish_catalog
from app.demo.catalog import build_demo_catalog
from app.models import Offer, PackageUnit, Product, Store

EXPORT = "/api/v1/catalog/export"
SEARCH = "/api/v1/products/search"


class TestSearch:
    def test_finds_products_containing_all_words(
        self, client: TestClient, user_headers: dict[str, str], demo_catalog: ImportReport
    ) -> None:
        response = client.get(SEARCH, headers=user_headers, params={"q": "молоко 2,5"})

        names = [product["name"] for product in response.json()]
        assert names
        assert all("Молоко 2,5%" in name for name in names[:3])

    def test_tolerates_typos(
        self, client: TestClient, user_headers: dict[str, str], demo_catalog: ImportReport
    ) -> None:
        response = client.get(SEARCH, headers=user_headers, params={"q": "кифир"})
        assert any("Кефир" in product["name"] for product in response.json())

    def test_returns_at_most_ten(
        self, client: TestClient, user_headers: dict[str, str], demo_catalog: ImportReport
    ) -> None:
        response = client.get(SEARCH, headers=user_headers, params={"q": "демо"})
        assert len(response.json()) == 10
        assert (
            client.get(SEARCH, headers=user_headers, params={"q": "демо", "limit": 11}).status_code
            == 422
        )

    def test_nothing_found_is_empty_list(
        self, client: TestClient, user_headers: dict[str, str], demo_catalog: ImportReport
    ) -> None:
        response = client.get(SEARCH, headers=user_headers, params={"q": "квантовый компьютер"})
        assert response.status_code == 200
        assert response.json() == []

    def test_products_not_sold_in_active_catalog_are_hidden(
        self,
        client: TestClient,
        session: Session,
        user_headers: dict[str, str],
        demo_catalog: ImportReport,
    ) -> None:
        session.add(
            Product(
                external_id="old-1",
                name="Молоко из прошлой загрузки",
                category="Молочные продукты",
                package_amount=1000,
                package_unit=PackageUnit.MILLILITER,
            )
        )
        session.commit()

        response = client.get(SEARCH, headers=user_headers, params={"q": "молоко прошлой"})
        names = [product["name"] for product in response.json()]
        assert "Молоко из прошлой загрузки" not in names

    def test_requires_auth(self, client: TestClient) -> None:
        assert client.get(SEARCH, params={"q": "молоко"}).status_code == 401


class TestProductDetail:
    def test_offers_are_marked_fresh_or_stale(
        self,
        client: TestClient,
        session: Session,
        user_headers: dict[str, str],
        demo_catalog: ImportReport,
    ) -> None:
        product_id = session.scalar(select(Product.id).order_by(Product.id).limit(1))
        session.execute(
            update(Offer)
            .where(Offer.product_id == product_id)
            .values(source_updated_at=datetime.now(UTC) - timedelta(hours=25))
        )
        session.commit()

        response = client.get(f"/api/v1/products/{product_id}", headers=user_headers)

        assert response.status_code == 200
        offers = response.json()["offers"]
        assert offers
        assert all(offer["is_fresh"] is False for offer in offers)
        prices = [offer["price_kopecks"] for offer in offers]
        assert prices == sorted(prices)

    def test_unknown_product(self, client: TestClient, user_headers: dict[str, str]) -> None:
        response = client.get("/api/v1/products/123456", headers=user_headers)
        assert response.status_code == 404
        assert response.json()["code"] == "product_not_found"


class TestStoresAndStatus:
    def test_stores_sorted_by_distance(
        self, client: TestClient, user_headers: dict[str, str], demo_catalog: ImportReport
    ) -> None:
        response = client.get(
            "/api/v1/stores",
            headers=user_headers,
            params={"latitude": 59.9571, "longitude": 30.3084},
        )
        distances = [store["distance_meters"] for store in response.json()]
        assert len(distances) == 6
        assert distances == sorted(distances)

    def test_catalog_status(
        self, client: TestClient, user_headers: dict[str, str], demo_catalog: ImportReport
    ) -> None:
        status = client.get("/api/v1/catalog", headers=user_headers).json()
        assert status["is_loaded"] is True
        assert status["is_synthetic"] is True
        assert status["products_count"] == 120
        assert status["offer_max_age_hours"] == 24
        # В демо-каталоге все цены свежие, но около 5 % товаров нет в наличии.
        assert 0 < status["fresh_offers_count"] < status["offers_count"]

    def test_catalog_not_loaded(self, client: TestClient, user_headers: dict[str, str]) -> None:
        assert client.get("/api/v1/catalog", headers=user_headers).json()["is_loaded"] is False


class TestExport:
    """Выгрузка для локального кэша iOS. Проверяем те же условия, что CatalogImportValidator."""

    def test_full_catalog_passes_client_validation(
        self, client: TestClient, user_headers: dict[str, str], demo_catalog: ImportReport
    ) -> None:
        body = client.get(EXPORT, headers=user_headers).json()

        assert body["import_id"] == demo_catalog.import_id
        assert body["is_synthetic"] is True
        assert len(body["stores"]) == 6
        assert len(body["offers"]) == demo_catalog.offers_count

        product_ids = [product["id"] for product in body["products"]]
        store_ids = [store["id"] for store in body["stores"]]
        offer_ids = [offer["id"] for offer in body["offers"]]
        for ids in (product_ids, store_ids, offer_ids):
            assert len(ids) == len(set(ids))
        for offer in body["offers"]:
            assert offer["product_id"] in set(product_ids)
            assert offer["store_id"] in set(store_ids)
            assert offer["price_kopecks"] > 0
            assert offer["currency"] == "RUB"
            assert offer["source_updated_at"].endswith("Z")
        assert all(product["package_amount"] > 0 for product in body["products"])

    def test_out_of_stock_and_stale_offers_are_included(
        self,
        client: TestClient,
        session: Session,
        user_headers: dict[str, str],
        demo_catalog: ImportReport,
    ) -> None:
        session.execute(
            update(Offer).values(source_updated_at=datetime.now(UTC) - timedelta(days=9))
        )
        session.commit()

        offers = client.get(EXPORT, headers=user_headers).json()["offers"]
        assert len(offers) == demo_catalog.offers_count
        assert {offer["in_stock"] for offer in offers} == {True, False}

    def test_inactive_store_is_left_out(
        self,
        client: TestClient,
        session: Session,
        user_headers: dict[str, str],
        demo_catalog: ImportReport,
    ) -> None:
        store_id = session.scalar(select(Store.id).order_by(Store.id).limit(1))
        session.execute(update(Store).where(Store.id == store_id).values(is_active=False))
        session.commit()

        body = client.get(EXPORT, headers=user_headers).json()
        assert store_id not in {store["id"] for store in body["stores"]}
        assert store_id not in {offer["store_id"] for offer in body["offers"]}

    def test_only_active_snapshot(
        self,
        client: TestClient,
        session: Session,
        user_headers: dict[str, str],
        demo_catalog: ImportReport,
    ) -> None:
        before = {
            offer["id"] for offer in client.get(EXPORT, headers=user_headers).json()["offers"]
        }
        now = datetime.now(UTC)
        newer = publish_catalog(
            session, build_demo_catalog(now), source_name="demo", file_sha256="newer", now=now
        )

        body = client.get(EXPORT, headers=user_headers).json()
        assert body["import_id"] == newer.import_id
        assert len(body["offers"]) == newer.offers_count
        assert {offer["id"] for offer in body["offers"]} == before

    def test_unchanged_catalog_is_not_sent_again(
        self, client: TestClient, user_headers: dict[str, str], demo_catalog: ImportReport
    ) -> None:
        first = client.get(EXPORT, headers=user_headers)
        etag = first.headers["ETag"]
        assert first.headers["Cache-Control"] == "private, no-cache"

        repeat = client.get(EXPORT, headers={**user_headers, "If-None-Match": etag})
        assert (repeat.status_code, repeat.content) == (304, b"")
        assert repeat.headers["ETag"] == etag

        other = client.get(EXPORT, headers={**user_headers, "If-None-Match": '"old"'})
        assert other.status_code == 200

    def test_requires_login_and_loaded_catalog(
        self, client: TestClient, user_headers: dict[str, str]
    ) -> None:
        assert client.get(EXPORT).status_code == 401
        response = client.get(EXPORT, headers=user_headers)
        assert (response.status_code, response.json()["code"]) == (503, "catalog_not_loaded")
