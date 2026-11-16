"""Аналоги товара для замены (F10).

Сначала жёсткие правила отсекают недопустимые замены, потом ML-модуль
упорядочивает оставшиеся товары по похожести названия. Правила основаны на
разметке аналогов в ML-модуле (ml/EVALUATION.md): тот же вид товара, тот же
процент в названии и фасовка в пределах ±30 %. Требование «другой бренд» из
разметки не берём: тот же бренд в похожей фасовке тоже нормальная замена.

Запрещённая правилами замена не попадает в список и не принимается при расчёте планов.
"""

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from smartcart_ml.text import parse_percent
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Product
from app.services import catalog, ml_matcher

MAX_ANALOGS = 3
PACKAGE_TOLERANCE = Decimal("0.3")
# Ниже этой похожести названий на нашем каталоге попадаются уже другие товары того же
# широкого вида: томатная паста и кисель (вид «Бакалея»). Отсутствие аналога допустимо (D04).
MIN_ANALOG_SCORE = 0.3

# Генератор данных команды помечает часть видов как «Йогурт (доп.)» или «Детское питание (доп.3)».
_EXTRA_MARK = re.compile(r"\s*\(доп\.?\d*\)$")


@dataclass(frozen=True)
class Analog:
    product: Product
    similarity: float
    min_price_kopecks: int


def substitution_problem(original: Product, replacement: Product) -> str | None:
    """Почему replacement не может заменить original. None, если замена допустима."""
    if replacement.id == original.id:
        return "это тот же товар"
    kind = _kind(original)
    if kind is None or kind != _kind(replacement):
        return "другой вид товара"
    if replacement.package_unit != original.package_unit:
        return "фасовка в других единицах"
    smallest = original.package_amount * (1 - PACKAGE_TOLERANCE)
    largest = original.package_amount * (1 + PACKAGE_TOLERANCE)
    if not smallest <= replacement.package_amount <= largest:
        return "фасовка отличается больше чем на 30 %"
    # Если процент указан только у одного товара, совпадение не доказано: такую замену не берём.
    if parse_percent(original.name) != parse_percent(replacement.name):
        return "другой процент (жирность, крепость)"
    return None


def find_analogs(
    session: Session, product: Product, now: datetime, max_age_hours: int
) -> list[Analog]:
    """До трёх допустимых аналогов, которые сейчас можно купить, от самого похожего."""
    active = catalog.get_active_import(session)
    if active is None:
        return []
    prices = catalog.cheapest_fresh_prices(session, active.id, now, max_age_hours)
    candidates = {
        candidate.id: candidate
        for candidate in session.scalars(select(Product).where(Product.id.in_(prices)))
        if substitution_problem(product, candidate) is None
    }
    if not candidates:
        return []

    matcher = ml_matcher.matcher_for(session, active)
    try:
        ranked = matcher.analogs(product.id, top_k=MAX_ANALOGS, candidate_ids=list(candidates))
    except ValueError:
        # Товара нет в текущем каталоге (остался от прошлой загрузки): сравнивать не с чем.
        return []
    return [
        Analog(candidates[row["product_id"]], row["score"], prices[row["product_id"]])
        for row in ranked
        if row["score"] >= MIN_ANALOG_SCORE
    ]


def _kind(product: Product) -> str | None:
    if not product.product_type:
        return None
    return _EXTRA_MARK.sub("", product.product_type).strip().lower()
