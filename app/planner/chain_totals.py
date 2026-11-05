"""Стоимость корзины отдельно в каждой сети (SCRUM-26, SCRUM-46, SCRUM-47).

Правила:
1. В суммы идёт только подтверждённая цена: свежая и с наличием (F04).
2. Цена товара в сети: самая низкая подтверждённая цена среди магазинов этой сети.
   При равной цене берём магазин с меньшим id, поэтому результат всегда одинаковый.
3. Строка: обычная цена упаковки × количество. Цена по карте показывается рядом,
   но в суммы не входит: условные скидки в MVP не считаются (F06).
4. Если подтверждённой цены нет, товар считается пропуском. Строка объясняет причину
   и показывает последнюю известную цену, но в суммы она не входит.
5. Итог сети есть только у полной корзины. У неполной есть сумма найденного и доля покрытия,
   а в рейтинге она всегда стоит ниже полных (F11).

Округления в суммах нет: цены в целых копейках, а количество целое (docs/planning.md).
"""

import enum
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from app.planner.models import BasketItem


class LineStatus(enum.StrEnum):
    AVAILABLE = "available"
    STALE = "stale"
    OUT_OF_STOCK = "out_of_stock"
    STOCK_UNKNOWN = "stock_unknown"
    NOT_SOLD = "not_sold"


@dataclass(frozen=True)
class ChainOffer:
    product_id: int
    store_id: int
    price_kopecks: int
    observed_at: datetime
    """Когда источник видел эту цену."""
    in_stock: bool | None
    is_fresh: bool
    card_price_kopecks: int | None = None
    price_type: str | None = None
    price_conditions: str | None = None

    @property
    def status(self) -> LineStatus:
        if not self.is_fresh:
            return LineStatus.STALE
        if self.in_stock is None:
            return LineStatus.STOCK_UNKNOWN
        return LineStatus.AVAILABLE if self.in_stock else LineStatus.OUT_OF_STOCK


@dataclass(frozen=True)
class ChainLine:
    product_id: int
    quantity: int
    offer: ChainOffer | None
    """Цена, на которой основана строка. None, если сеть не продаёт товар."""

    @property
    def status(self) -> LineStatus:
        return self.offer.status if self.offer else LineStatus.NOT_SOLD

    @property
    def is_counted(self) -> bool:
        return self.status is LineStatus.AVAILABLE

    @property
    def total_kopecks(self) -> int | None:
        if self.offer is None or not self.is_counted:
            return None
        return self.offer.price_kopecks * self.quantity


@dataclass(frozen=True)
class ChainTotal:
    chain: str
    lines: tuple[ChainLine, ...]

    @property
    def missing_product_ids(self) -> tuple[int, ...]:
        return tuple(line.product_id for line in self.lines if not line.is_counted)

    @property
    def is_complete(self) -> bool:
        return not self.missing_product_ids

    @property
    def found_items_count(self) -> int:
        return len(self.lines) - len(self.missing_product_ids)

    @property
    def coverage_percent(self) -> int:
        """Доля найденных позиций. Округление вниз: 100 % бывает только у полной корзины."""
        return self.found_items_count * 100 // len(self.lines)

    @property
    def found_total_kopecks(self) -> int:
        return sum(line.total_kopecks or 0 for line in self.lines)

    @property
    def total_kopecks(self) -> int | None:
        return self.found_total_kopecks if self.is_complete else None

    @property
    def oldest_observed_at(self) -> datetime | None:
        """Самая старая цена в суммах: насколько актуален итог сети."""
        observed = [line.offer.observed_at for line in self.lines if line.offer and line.is_counted]
        return min(observed, default=None)

    def sort_key(self) -> tuple[int, int, str]:
        """Сначала полные корзины от дешёвой к дорогой, потом неполные по числу пропусков."""
        return (len(self.missing_product_ids), self.total_kopecks or 0, self.chain)


def chain_totals(
    basket: Sequence[BasketItem], offers: Iterable[ChainOffer], store_chains: Mapping[int, str]
) -> list[ChainTotal]:
    """Считает корзину в каждой сети из `store_chains` (store_id -> название сети)."""
    by_chain: dict[tuple[str, int], list[ChainOffer]] = defaultdict(list)
    for offer in offers:
        chain = store_chains.get(offer.store_id)
        if chain is not None:
            by_chain[(chain, offer.product_id)].append(offer)

    totals = [
        ChainTotal(
            chain,
            tuple(
                ChainLine(
                    item.product_id, item.quantity, _best_offer(by_chain[chain, item.product_id])
                )
                for item in basket
            ),
        )
        for chain in sorted(set(store_chains.values()))
    ]
    return sorted(totals, key=ChainTotal.sort_key)


def _best_offer(offers: Sequence[ChainOffer]) -> ChainOffer | None:
    usable = [offer for offer in offers if offer.status is LineStatus.AVAILABLE]
    if usable:
        return min(usable, key=lambda offer: (offer.price_kopecks, offer.store_id))
    if offers:
        # Подтверждённой цены нет: показываем самые свежие сведения о товаре.
        latest = max(offer.observed_at for offer in offers)
        newest = [offer for offer in offers if offer.observed_at == latest]
        return min(newest, key=lambda offer: (offer.price_kopecks, offer.store_id))
    return None
