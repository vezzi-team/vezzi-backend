"""Импорт каталога: формат файла, отказы по строкам, идемпотентность, атомарность (D02, N04)."""

from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from httpx2 import Response
from openpyxl import Workbook, load_workbook
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.catalog_import import publisher
from app.catalog_import.columns import SHEETS
from app.catalog_import.publisher import publish_catalog
from app.catalog_import.reader import CatalogFormatError, read_catalog
from app.catalog_import.template import write_template
from app.models import CatalogImport, ImportStatus, Offer, Product, Store

IMPORTS = "/api/v1/admin/catalog/imports"
MOSCOW = ZoneInfo("Europe/Moscow")
NOW_TEXT = (datetime.now(MOSCOW) - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")


def workbook_bytes(
    offers: list[list[Any]] | None = None,
    drop_sheet: str | None = None,
    products: list[list[Any]] | None = None,
) -> bytes:
    workbook = Workbook()
    workbook.remove(workbook.active)
    sheets = {
        "stores": [
            ["store_id", "chain_name", "store_name", "address", "latitude", "longitude"],
            [1, "Сеть А", "А-1", "Адрес 1", 59.9566, 30.3165],
            [2, "Сеть Б", "Б-1", "Адрес 2", 59.9580, 30.3049],
        ],
        "products": products
        or [
            ["product_id", "product_name", "category", "quantity", "unit"],
            [10, "Молоко 2,5%, 930 мл", "Молочные продукты", 0.93, "л"],
            [11, "Хлеб, 400 г", "Хлеб", 400, "г"],
        ],
        "offers": [
            ["product_id", "store_id", "price", "in_stock", "updated_at", "match_status"],
            *(
                offers
                or [
                    [10, 1, 89.99, True, NOW_TEXT, "matched"],
                    [10, 2, 92.5, True, NOW_TEXT, "matched"],
                    [11, 1, 45, True, NOW_TEXT, "matched"],
                    [11, 2, None, True, NOW_TEXT, "matched"],
                    [11, 2, 47, True, NOW_TEXT, "needs_review"],
                    [99, 1, 10, True, NOW_TEXT, "matched"],
                ]
            ),
        ],
        "carts": [["cart_id"], [1]],
    }
    for name, rows in sheets.items():
        if name == drop_sheet:
            continue
        sheet = workbook.create_sheet(name)
        for row in rows:
            sheet.append(row)
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def upload(client: TestClient, headers: dict[str, str], content: bytes, **form: str) -> Response:
    return client.post(
        IMPORTS, headers=headers, files={"file": ("catalog.xlsx", content)}, data=form
    )


class TestReader:
    def test_valid_rows_are_accepted_and_bad_rows_explained(self) -> None:
        catalog = read_catalog(BytesIO(workbook_bytes()), MOSCOW)

        assert len(catalog.stores) == 2
        assert len(catalog.products) == 2
        assert len(catalog.offers) == 3
        messages = sorted(error.message for error in catalog.errors)
        assert messages == [
            "не заполнена колонка price",
            "товар 99 не найден на листе products",
            "товар не сопоставлен (match_status=needs_review)",
        ]

    def test_weighted_products_and_their_prices_are_skipped(self) -> None:
        products = [
            ["product_id", "product_name", "category", "quantity", "unit", "attributes_json"],
            [10, "Молоко 2,5%, 930 мл", "Молочные продукты", 0.93, "л", '{"sold_by": "штучный"}'],
            [11, "Филе куриное, кг", "Мясо", 1, "кг", '{"sold_by": "весовой"}'],
        ]
        offers = [
            [10, 1, 89.99, True, NOW_TEXT, "matched"],
            [11, 1, 389, True, NOW_TEXT, "matched"],
            [11, 2, 399, True, NOW_TEXT, "matched"],
        ]
        catalog = read_catalog(BytesIO(workbook_bytes(offers, products=products)), MOSCOW)

        assert [product.external_id for product in catalog.products] == ["10"]
        assert [offer.product_external_id for offer in catalog.offers] == ["10"]
        assert (catalog.skipped_weighted_products, catalog.skipped_weighted_offers) == (1, 2)
        assert catalog.errors == []

    def test_duplicate_offer_is_rejected(self) -> None:
        duplicate = [[10, 1, 89.99, True, NOW_TEXT, "matched"]] * 2
        catalog = read_catalog(BytesIO(workbook_bytes(offers=duplicate)), MOSCOW)
        assert len(catalog.offers) == 1
        assert "повтор" in catalog.errors[0].message

    def test_missing_sheet_is_a_format_error(self) -> None:
        with pytest.raises(CatalogFormatError, match="offers"):
            read_catalog(BytesIO(workbook_bytes(drop_sheet="offers")), MOSCOW)

    def test_not_an_excel_file(self) -> None:
        with pytest.raises(CatalogFormatError, match="xlsx"):
            read_catalog(BytesIO(b"name,price\nmilk,10"), MOSCOW)

    def test_template_is_accepted_by_reader(self, tmp_path: Path) -> None:
        path = tmp_path / "template.xlsx"
        write_template(path)

        assert set(load_workbook(path).sheetnames) == {"Инструкция", *SHEETS}
        catalog = read_catalog(path, MOSCOW)
        assert (len(catalog.stores), len(catalog.products), len(catalog.offers)) == (1, 1, 1)


class TestPublishing:
    def test_publish_and_reimport_same_file(self, session: Session) -> None:
        content = workbook_bytes()
        catalog = read_catalog(BytesIO(content), MOSCOW)
        now = datetime.now(UTC)

        first = publish_catalog(session, catalog, source_name="a.xlsx", file_sha256="abc", now=now)
        second = publish_catalog(session, catalog, source_name="a.xlsx", file_sha256="abc", now=now)

        assert first.status == "published"
        assert (first.offers_count, first.rejected_rows_count) == (3, 3)
        assert second.status == "unchanged"
        assert session.scalar(select(func.count()).select_from(Offer)) == 3
        assert session.scalar(select(func.count()).select_from(Product)) == 2

    def test_new_import_replaces_active_snapshot_and_updates_products(
        self, session: Session
    ) -> None:
        now = datetime.now(UTC)
        catalog = read_catalog(BytesIO(workbook_bytes()), MOSCOW)
        publish_catalog(session, catalog, source_name="a", file_sha256="v1", now=now)
        report = publish_catalog(session, catalog, source_name="b", file_sha256="v2", now=now)

        statuses = session.scalars(select(CatalogImport.status).order_by(CatalogImport.id)).all()
        assert statuses == [ImportStatus.ARCHIVED, ImportStatus.ACTIVE]
        assert session.scalar(select(func.count()).select_from(Product)) == 2
        active_offers = (
            select(func.count()).select_from(Offer).where(Offer.import_id == report.import_id)
        )
        assert session.scalar(active_offers) == 3

    def test_failure_keeps_previous_snapshot(
        self, session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        now = datetime.now(UTC)
        catalog = read_catalog(BytesIO(workbook_bytes()), MOSCOW)
        first = publish_catalog(session, catalog, source_name="a", file_sha256="v1", now=now)

        def broken_insert(*_: object) -> None:
            raise RuntimeError("диск переполнен")

        monkeypatch.setattr(publisher, "insert", broken_insert)
        with pytest.raises(RuntimeError):
            publish_catalog(session, catalog, source_name="b", file_sha256="v2", now=now)

        active = session.scalar(
            select(CatalogImport).where(CatalogImport.status == ImportStatus.ACTIVE)
        )
        assert active is not None
        assert active.id == first.import_id

    def test_reimport_does_not_refresh_old_prices(self, session: Session) -> None:
        old = (datetime.now(MOSCOW) - timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")
        catalog = read_catalog(
            BytesIO(workbook_bytes(offers=[[10, 1, 50, True, old, "matched"]])), MOSCOW
        )
        publish_catalog(session, catalog, source_name="a", file_sha256="v1", now=datetime.now(UTC))

        stored = session.scalar(select(Offer.source_updated_at))
        assert stored is not None
        assert datetime.now(UTC) - stored > timedelta(days=2)

    def test_shift_timestamps_makes_newest_price_current(self, session: Session) -> None:
        old = (datetime.now(MOSCOW) - timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")
        catalog = read_catalog(
            BytesIO(workbook_bytes(offers=[[10, 1, 50, True, old, "matched"]])), MOSCOW
        )
        now = datetime.now(UTC)
        report = publish_catalog(
            session, catalog, source_name="a", file_sha256="v1", now=now, shift_timestamps=True
        )

        assert report.timestamps_shifted is True
        assert session.scalar(select(Offer.source_updated_at)) == now

    def test_future_timestamps_are_rejected(self, session: Session) -> None:
        future = (datetime.now(MOSCOW) + timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
        rows = [[10, 1, 50, True, future, "matched"], [11, 1, 40, True, NOW_TEXT, "matched"]]
        catalog = read_catalog(BytesIO(workbook_bytes(offers=rows)), MOSCOW)
        report = publish_catalog(
            session, catalog, source_name="a", file_sha256="v1", now=datetime.now(UTC)
        )

        assert report.offers_count == 1
        assert report.errors[-1].message == "время обновления цены в будущем"


class TestAdminEndpoint:
    def test_admin_can_upload(self, client: TestClient, admin_headers: dict[str, str]) -> None:
        # openpyxl пишет в файл время сохранения, поэтому файл создаём один раз.
        content = workbook_bytes()
        response = upload(client, admin_headers, content)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "published"
        assert body["offers_count"] == 3
        assert body["fresh_offers_count"] == 3
        assert body["is_synthetic"] is False
        assert len(body["errors"]) == 3

        repeat = upload(client, admin_headers, content)
        assert repeat.json()["status"] == "unchanged"

        history = client.get(IMPORTS, headers=admin_headers).json()
        assert [item["status"] for item in history] == ["active"]

    def test_admin_can_mark_data_as_synthetic(
        self, client: TestClient, admin_headers: dict[str, str]
    ) -> None:
        content = workbook_bytes()
        upload(client, admin_headers, content)

        marked = upload(client, admin_headers, content, is_synthetic="true").json()
        assert (marked["status"], marked["is_synthetic"]) == ("published", True)
        assert client.get("/api/v1/catalog", headers=admin_headers).json()["is_synthetic"] is True

    def test_regular_user_is_forbidden(
        self, client: TestClient, user_headers: dict[str, str]
    ) -> None:
        response = upload(client, user_headers, workbook_bytes())
        assert response.status_code == 403
        assert client.get(IMPORTS, headers=user_headers).status_code == 403

    def test_broken_file(self, client: TestClient, admin_headers: dict[str, str]) -> None:
        response = upload(client, admin_headers, b"definitely not excel")
        assert response.status_code == 422
        assert response.json()["code"] == "invalid_catalog_file"

    def test_stores_are_updated_by_external_id(
        self, client: TestClient, session: Session, admin_headers: dict[str, str]
    ) -> None:
        upload(client, admin_headers, workbook_bytes())
        upload(client, admin_headers, workbook_bytes(), shift_timestamps="true")
        assert session.scalar(select(func.count()).select_from(Store)) == 2
