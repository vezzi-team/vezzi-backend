"""SCRUM-48: сверка расчёта backend с независимым эталоном по таблице команды.

Эталон строит tests/reference/build_reference.py, он не использует код backend.
Здесь каталог проходит настоящий импорт, корзины создаются через API, а ответ сверяется
с эталоном: количества, фасовки, цены, суммы, пропуски и порядок сетей.

Отчёт: REFERENCE_REPORT=docs/reference-check.md uv run pytest tests/api/test_reference_totals.py
"""

import csv
import json
import os
from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.catalog_import.publisher import publish_catalog
from app.catalog_import.reader import read_catalog
from app.core.config import get_settings
from app.models import Product, Store, User
from app.schemas.comparison import ChainComparison, ChainLineRead, ChainTotalRead
from app.services.comparison import compare_chains
from tests.api.plan_helpers import CARTS

REFERENCE = Path(__file__).parents[1] / "reference"
MOSCOW = ZoneInfo("Europe/Moscow")


def read_csv(name: str) -> list[dict[str, str]]:
    with (REFERENCE / name).open(encoding="utf-8") as file:
        return list(csv.DictReader(file))


def kopecks(rubles: str) -> int | None:
    if not rubles:
        return None
    value = Decimal(rubles) * 100
    assert value == value.to_integral_value(), f"эталон с долями копейки: {rubles}"
    return int(value)


def compare_line(expected: dict[str, str], line: ChainLineRead, external_ids: dict) -> list[str]:
    store_id = external_ids[line.store.id] if line.store else ""
    amount, unit = Decimal(expected["package_amount"]), expected["package_unit"]
    pairs = {
        "количество": (int(expected["quantity"]), line.quantity),
        "фасовка": (
            (amount, unit),
            (Decimal(str(line.product.package_amount)), line.product.package_unit.value),
        ),
        "статус": (expected["status"], line.status.value),
        "магазин": (expected["store_id"], store_id),
        "цена": (kopecks(expected["unit_price_rub"]), line.unit_price_kopecks),
        "сумма строки": (kopecks(expected["line_total_rub"]), line.total_kopecks),
    }
    return [
        f"{name}: эталон {want}, backend {got}"
        for name, (want, got) in pairs.items()
        if want != got
    ]


def compare_total(expected: dict[str, str], total: ChainTotalRead, rank: int) -> list[str]:
    pairs = {
        "позиций": (int(expected["items"]), total.items_count),
        "найдено": (int(expected["found_items"]), total.found_items_count),
        "покрытие": (int(expected["coverage_percent"]), total.coverage_percent),
        "полная": (expected["is_complete"] == "True", total.is_complete),
        "сумма найденного": (kopecks(expected["found_total_rub"]), total.found_total_kopecks),
        "итог": (kopecks(expected["total_rub"]), total.total_kopecks),
        "место": (int(expected["rank"]), rank),
    }
    return [
        f"{name}: эталон {want}, backend {got}"
        for name, (want, got) in pairs.items()
        if want != got
    ]


def rubles(value: int | None) -> str:
    return "нет" if value is None else f"{value / 100:.2f}".replace(".", ",")


def write_report(
    path: Path,
    summary: dict,
    stats: dict[str, dict[str, int]],
    problems: list[str],
    example: ChainComparison,
) -> None:
    wrong = summary["plans_with_wrong_total"]
    report = [
        "# Сверка расчёта с эталоном (SCRUM-48)",
        "",
        "Файл создан автоматически тестом `tests/api/test_reference_totals.py`.",
        "",
        f"Источник: `{summary['source']}` от команды данных. Сети: {', '.join(summary['chains'])}.",
        f"Момент расчёта: {summary['now_moscow']} по Москве (час после самой свежей цены в файле).",
        "",
        "Эталон посчитан скриптом `tests/reference/build_reference.py`: он читает таблицу",
        "напрямую, не использует код backend и считает в рублях через Decimal.",
        "Backend считает в целых копейках.",
        "**Это не ручной эталон Analytics (SCRUM-53):** он ещё не готов. Когда появится,",
        "его итоги нужно подставить в сверку.",
        "",
        "## Результат",
        "",
        f"**Расхождений с backend: {len(problems)}.**",
        "",
        "| Сценарий | Лимит свежести | Корзин | Сравнено строк | Сравнено итогов | Расхождений |",
        "|---|---|---|---|---|---|",
    ]
    for scenario, row in stats.items():
        report.append(
            f"| `{scenario}` | {summary['scenarios'][scenario]} ч | {row['carts']} "
            f"| {row['lines']} | {row['totals']} | {row['problems']} |"
        )
    report += [
        "",
        "Что сверялось: количества, фасовки (г, мл, шт, м после перевода единиц), статус строки,",
        "магазин, цена, сумма строки, сумма найденного, итог, доля покрытия и место сети.",
        "Округление: каждая сумма эталона в рублях перешла в копейки без остатка и совпала точно.",
        "",
    ]
    report += [f"- {problem}" for problem in problems[:50]]
    report += [
        "## Пример для проверки на калькуляторе",
        "",
        "Самая наполненная корзина таблицы, сценарий `all_fresh`.",
        "",
        "| Сеть | Товар | Кол-во | Цена, ₽ | Сумма, ₽ | Статус |",
        "|---|---|---|---|---|---|",
    ]
    for chain in example.chains:
        for line in chain.lines:
            report.append(
                f"| {chain.chain} | {line.product.name} | {line.quantity} "
                f"| {rubles(line.unit_price_kopecks)} | {rubles(line.total_kopecks)} "
                f"| {line.status.value} |"
            )
        report.append(
            f"| **{chain.chain}** | **итог** | | | **{rubles(chain.total_kopecks)}** "
            f"| покрытие {chain.coverage_percent} % |"
        )
    report += [
        "",
        "## Расхождения в самой таблице команды",
        "",
        "Листы `plans` и `plan_items` заполнены тестовыми данными, backend их не загружает.",
        "",
        f"- Весовых позиций в корзинах таблицы: {summary['weighted_items_excluded']} из "
        f"{summary['items_in_table']}. Они исключены из сверки: в MVP их нет.",
        f"- В {len(wrong)} планах из {summary['plans_in_table']} `total_estimated_price` не равен "
        "сумме позиций.",
        f"- Планов с датой позже самой свежей цены: {len(summary['plans_from_future'])}.",
        "",
        "| План | Сумма в таблице, ₽ | Сумма позиций, ₽ |",
        "|---|---|---|",
    ]
    report += [f"| {row['plan_id']} | {row['stated']} | {row['sum']} |" for row in wrong]
    path.write_text("\n".join(report) + "\n", encoding="utf-8")


def test_backend_matches_reference(
    client: TestClient, session: Session, user_headers: dict[str, str]
) -> None:
    summary = json.loads((REFERENCE / "summary.json").read_text(encoding="utf-8"))
    now = datetime.fromisoformat(summary["now_moscow"]).replace(tzinfo=MOSCOW).astimezone(UTC)
    catalog = read_catalog(REFERENCE / "catalog.xlsx", MOSCOW)
    publish_catalog(
        session,
        catalog,
        source_name="reference",
        file_sha256="reference",
        now=now,
        mark_synthetic=True,
    )
    assert catalog.errors == []

    product_ids = {p.external_id: p.id for p in session.scalars(select(Product))}
    external_store_ids = {s.id: s.external_id for s in session.scalars(select(Store))}
    user = session.scalar(select(User).where(User.email == "alice@example.com"))
    assert user is not None

    lines = read_csv("lines.csv")
    totals = read_csv("totals.csv")
    contents: dict[str, dict[str, str]] = defaultdict(dict)
    for row in lines:
        contents[row["cart_id"]][row["product_id"]] = row["quantity"]

    cart_uuids = {}
    for cart_id, items in contents.items():
        uuid = client.post(CARTS, headers=user_headers, json={"name": f"Корзина {cart_id}"}).json()[
            "id"
        ]
        cart_uuids[cart_id] = uuid
        for product_id, quantity in items.items():
            response = client.post(
                f"{CARTS}/{uuid}/items",
                headers=user_headers,
                json={"product_id": product_ids[product_id], "quantity": int(quantity)},
            )
            assert response.status_code == 200, response.text

    expected_lines = {(r["scenario"], r["cart_id"], r["chain"], r["product_id"]): r for r in lines}
    expected_totals = {(r["scenario"], r["cart_id"], r["chain"]): r for r in totals}
    problems: list[str] = []
    stats: dict[str, dict[str, int]] = {}
    example = None
    example_lines = 0

    for scenario, max_age_hours in summary["scenarios"].items():
        settings = get_settings().model_copy(update={"offer_max_age_hours": max_age_hours})
        row = {"carts": len(cart_uuids), "lines": 0, "totals": 0, "problems": 0}
        for cart_id, uuid in cart_uuids.items():
            result = compare_chains(session, settings, user, uuid, summary["chains"], now)
            found_lines = sum(chain.found_items_count for chain in result.chains)
            if scenario == "all_fresh" and found_lines > example_lines:
                example, example_lines = result, found_lines
            for rank, chain in enumerate(result.chains, start=1):
                found = compare_total(expected_totals[scenario, cart_id, chain.chain], chain, rank)
                row["totals"] += 1
                row["problems"] += len(found)
                problems += [f"`{scenario}`, корзина {cart_id}, {chain.chain}: {p}" for p in found]
                for line in chain.lines:
                    external_id = next(k for k, v in product_ids.items() if v == line.product.id)
                    expected = expected_lines[scenario, cart_id, chain.chain, external_id]
                    found = compare_line(expected, line, external_store_ids)
                    row["lines"] += 1
                    row["problems"] += len(found)
                    problems += [
                        f"`{scenario}`, корзина {cart_id}, {chain.chain}, товар {external_id}: {p}"
                        for p in found
                    ]
        stats[scenario] = row

    report_path = os.environ.get("REFERENCE_REPORT")
    if report_path and example is not None:
        write_report(Path(report_path), summary, stats, problems, example)

    assert sum(row["lines"] for row in stats.values()) == len(lines)
    assert sum(row["totals"] for row in stats.values()) == len(totals)
    assert problems == []
    assert example is not None
