"""Правила допустимой замены (F10) без базы данных."""

from decimal import Decimal

import pytest

from app.models import PackageUnit, Product
from app.services.analogs import substitution_problem


def product(
    product_id: int,
    name: str,
    amount: int = 930,
    unit: PackageUnit = PackageUnit.MILLILITER,
    product_type: str | None = "Молоко",
    brand: str | None = None,
) -> Product:
    return Product(
        id=product_id,
        name=name,
        brand=brand,
        category="Молочные продукты",
        product_type=product_type,
        package_amount=Decimal(amount),
        package_unit=unit,
    )


MILK = product(1, "Простоквашино Молоко 2,5%, 930 мл", brand="Простоквашино")


@pytest.mark.parametrize(
    "replacement",
    [
        product(2, "Домик в деревне Молоко 2,5%, 950 мл", 950, brand="Домик в деревне"),
        product(3, "Простоквашино Молоко 2,5%, 1 л", 1000, brand="Простоквашино"),
        product(4, "Экомилк Молоко 2,5%, 900 мл", 900, product_type="Молоко (доп.)"),
        product(5, "Молоко 2,5%, 651 мл", 651, product_type="молоко"),
    ],
)
def test_allowed_replacements(replacement: Product) -> None:
    assert substitution_problem(MILK, replacement) is None


@pytest.mark.parametrize(
    ("replacement", "reason"),
    [
        (MILK, "это тот же товар"),
        (product(2, "Простоквашино Кефир 2,5%, 930 мл", product_type="Кефир"), "другой вид"),
        (product(3, "Молоко 2,5%, 930 мл", product_type=None), "другой вид"),
        (product(4, "Молоко 2,5%, 930 г", unit=PackageUnit.GRAM), "в других единицах"),
        (product(5, "Молоко 2,5%, 1,4 л", 1400), "больше чем на 30 %"),
        (product(6, "Молоко 2,5%, 500 мл", 500), "больше чем на 30 %"),
        (product(7, "Молоко 3,2%, 930 мл"), "другой процент"),
        (product(8, "Молоко козье, 930 мл"), "другой процент"),
    ],
)
def test_forbidden_replacements(replacement: Product, reason: str) -> None:
    problem = substitution_problem(MILK, replacement)
    assert problem is not None
    assert reason in problem
