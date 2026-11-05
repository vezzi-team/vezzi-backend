"""Независимый эталон для SCRUM-48: считает корзины из таблицы команды без кода backend.

Скрипт намеренно ничего не импортирует из app/. Если бы эталон и backend делили код,
одна и та же ошибка прошла бы незамеченной. Суммы здесь считаются в рублях через Decimal,
а backend считает в целых копейках: совпадение до копейки заодно проверяет округление.

Запуск из корня репозитория:
    uv run python tests/reference/build_reference.py "/путь/Умная_корзина.xlsx"

Рядом со скриптом появятся:
    catalog.xlsx   часть таблицы: только нужные магазины, товары и цены
    lines.csv      ожидаемая строка для каждой корзины, сети и сценария
    totals.csv     ожидаемый итог для каждой корзины, сети и сценария
    summary.json   счётчики и ошибки, найденные в самой таблице команды
"""

import csv
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

from openpyxl import Workbook, load_workbook

HERE = Path(__file__).parent
# Московское время, как в таблице: через час после самой свежей цены в файле.
NOW = datetime(2026, 10, 30, 9, 0)  # noqa: DTZ001 (в таблице время без пояса)
SCENARIOS = {"all_fresh": 264, "rule_24h": 24}
UNIT_FACTORS = {
    "г": ("g", 1),
    "кг": ("g", 1000),
    "мл": ("ml", 1),
    "л": ("ml", 1000),
    "шт": ("pcs", 1),
    "м": ("m", 1),
}


def read_sheet(workbook, name):
    rows = workbook[name].iter_rows(values_only=True)
    header = list(next(rows))
    return header, [dict(zip(header, row, strict=False)) for row in rows if row[0] is not None]


def to_decimal(value):
    return Decimal(repr(value)) if isinstance(value, float) else Decimal(value)


def is_weighted(product):
    return json.loads(product["attributes_json"]).get("sold_by", "").strip().lower() == "весовой"


def expected_package(product):
    unit, factor = UNIT_FACTORS[product["unit"]]
    return to_decimal(product["quantity"]) * factor, unit


def choose_offer(offers, cutoff):
    """Возвращает статус строки и цену, на которой она основана."""
    fresh = [o for o in offers if datetime.fromisoformat(o["updated_at"]) >= cutoff]
    confirmed = [o for o in fresh if o["in_stock"] is True]
    if confirmed:
        return "available", min(confirmed, key=lambda o: (to_decimal(o["price"]), o["store_id"]))
    if not offers:
        return "not_sold", None
    latest = max(o["updated_at"] for o in offers)
    newest = [o for o in offers if o["updated_at"] == latest]
    offer = min(newest, key=lambda o: (to_decimal(o["price"]), o["store_id"]))
    if datetime.fromisoformat(offer["updated_at"]) < cutoff:
        return "stale", offer
    return ("out_of_stock" if offer["in_stock"] is False else "stock_unknown"), offer


def write_catalog(path, sheets):
    workbook = Workbook()
    workbook.remove(workbook.active)
    for name, (header, rows) in sheets.items():
        sheet = workbook.create_sheet(name)
        sheet.append(header)
        for row in rows:
            sheet.append([row[column] for column in header])
    workbook.save(path)


def write_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def check_team_plans(plans, plan_items, offers_by_id):
    """Сходятся ли суммы планов в таблице команды и нет ли планов из будущего."""
    items = defaultdict(list)
    for item in plan_items:
        items[item["plan_id"]].append(item)
    wrong_totals, future = [], []
    for plan in plans:
        total = sum(
            to_decimal(offers_by_id[i["preferred_offer_id"]]["price"]) * i["quantity"]
            for i in items[plan["plan_id"]]
        )
        if total != to_decimal(plan["total_estimated_price"]):
            stated = str(plan["total_estimated_price"])
            wrong_totals.append({"plan_id": plan["plan_id"], "stated": stated, "sum": str(total)})
        if datetime.fromisoformat(plan["created_at"]) > NOW:
            future.append(plan["plan_id"])
    return wrong_totals, future


def main(source):
    workbook = load_workbook(source, read_only=True, data_only=True)
    store_header, stores = read_sheet(workbook, "stores")
    product_header, products = read_sheet(workbook, "products")
    offer_header, offers = read_sheet(workbook, "offers")
    _, carts = read_sheet(workbook, "carts")
    _, cart_items = read_sheet(workbook, "cart_items")
    _, plans = read_sheet(workbook, "plans")
    _, plan_items = read_sheet(workbook, "plan_items")

    products_by_id = {product["product_id"]: product for product in products}
    chain_of_store = {store["store_id"]: store["chain_name"] for store in stores}
    chains = sorted(set(chain_of_store.values()))
    carts_contents = defaultdict(list)
    weighted_items = 0
    for item in sorted(cart_items, key=lambda row: row["cart_item_id"]):
        if is_weighted(products_by_id[item["product_id"]]):
            weighted_items += 1
        else:
            carts_contents[item["cart_id"]].append((item["product_id"], item["quantity"]))

    used = {item["product_id"] for item in cart_items}
    used_offers = [o for o in offers if o["product_id"] in used and o["store_id"] in chain_of_store]
    write_catalog(
        HERE / "catalog.xlsx",
        {
            "stores": (store_header, [s for s in stores if s["store_id"] in chain_of_store]),
            "products": (product_header, [p for p in products if p["product_id"] in used]),
            "offers": (offer_header, used_offers),
        },
    )

    offers_of = defaultdict(list)
    for offer in used_offers:
        offers_of[(chain_of_store[offer["store_id"]], offer["product_id"])].append(offer)

    lines, totals = [], []
    for scenario, max_age_hours in SCENARIOS.items():
        cutoff = NOW - timedelta(hours=max_age_hours)
        for cart_id, contents in sorted(carts_contents.items()):
            cart_totals = []
            for chain in chains:
                found_total = Decimal(0)
                found = 0
                for product_id, quantity in contents:
                    status, offer = choose_offer(offers_of[(chain, product_id)], cutoff)
                    price = to_decimal(offer["price"]) if offer else None
                    line_total = price * quantity if status == "available" else None
                    if line_total is not None:
                        found += 1
                        found_total += line_total
                    amount, unit = expected_package(products_by_id[product_id])
                    lines.append(
                        {
                            "scenario": scenario,
                            "cart_id": cart_id,
                            "chain": chain,
                            "product_id": product_id,
                            "quantity": quantity,
                            "package_amount": amount,
                            "package_unit": unit,
                            "status": status,
                            "store_id": offer["store_id"] if offer else "",
                            "unit_price_rub": price if price is not None else "",
                            "line_total_rub": line_total if line_total is not None else "",
                        }
                    )
                is_complete = found == len(contents)
                cart_totals.append(
                    {
                        "scenario": scenario,
                        "cart_id": cart_id,
                        "chain": chain,
                        "items": len(contents),
                        "found_items": found,
                        "coverage_percent": found * 100 // len(contents),
                        "is_complete": is_complete,
                        "found_total_rub": found_total,
                        "total_rub": found_total if is_complete else "",
                    }
                )
            ranked = sorted(
                cart_totals,
                key=lambda row: (
                    row["items"] - row["found_items"],
                    row["total_rub"] if row["is_complete"] else 0,
                    row["chain"],
                ),
            )
            for rank, row in enumerate(ranked, start=1):
                row["rank"] = rank
            totals.extend(cart_totals)

    write_csv(HERE / "lines.csv", lines)
    write_csv(HERE / "totals.csv", totals)

    offers_by_id = {offer["offer_id"]: offer for offer in offers}
    wrong_totals, future_plans = check_team_plans(plans, plan_items, offers_by_id)
    summary = {
        "source": Path(source).name,
        "now_moscow": NOW.isoformat(),
        "chains": chains,
        "scenarios": SCENARIOS,
        "carts_in_table": len(carts),
        "carts_checked": len(carts_contents),
        "items_in_table": len(cart_items),
        "weighted_items_excluded": weighted_items,
        "plans_in_table": len(plans),
        "plans_with_wrong_total": wrong_totals,
        "plans_from_future": future_plans,
    }
    (HERE / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Корзин: {len(carts_contents)}, строк: {len(lines)}, итогов: {len(totals)}")


if __name__ == "__main__":
    main(sys.argv[1])
