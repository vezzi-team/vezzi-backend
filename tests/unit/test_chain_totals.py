"""Сумма корзины по сетям. Контрольные примеры посчитаны вручную, они же в docs/planning.md."""

import random
from datetime import UTC, datetime, timedelta
from typing import ClassVar

from app.planner.chain_totals import ChainOffer, LineStatus, chain_totals
from app.planner.models import BasketItem

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)
MILK, BREAD, PASTA = 1, 2, 3
BASKET = [BasketItem(MILK, 2), BasketItem(BREAD, 1), BasketItem(PASTA, 3)]
# У сети «А» два магазина (10 и 11), у «Б» один (20), у «В» один (30), и в нём нет хлеба.
STORE_CHAINS = {10: "А", 11: "А", 20: "Б", 30: "В"}


def offer(product_id: int, store_id: int, kopecks: int, **changes: object) -> ChainOffer:
    values: dict = {"observed_at": NOW, "in_stock": True, "is_fresh": True, **changes}
    return ChainOffer(product_id, store_id, kopecks, **values)


OFFERS = [
    offer(MILK, 10, 8990),
    offer(MILK, 11, 8790),
    offer(MILK, 20, 9450),
    offer(MILK, 30, 8500),
    offer(BREAD, 10, 4500),
    offer(BREAD, 11, 4500),
    offer(BREAD, 20, 3990),
    offer(PASTA, 10, 7999),
    offer(PASTA, 11, 8199),
    offer(PASTA, 20, 7500),
    offer(PASTA, 30, 6900),
]


def test_reference_example() -> None:
    b, a, v = chain_totals(BASKET, OFFERS, STORE_CHAINS)

    assert (b.chain, b.total_kopecks) == ("Б", 45390)  # 94,50×2 + 39,90 + 75,00×3 = 453,90 ₽
    assert [line.total_kopecks for line in b.lines] == [18900, 3990, 22500]

    assert (a.chain, a.total_kopecks) == ("А", 46077)  # 87,90×2 + 45,00 + 79,99×3 = 460,77 ₽
    assert [line.offer and line.offer.store_id for line in a.lines] == [11, 10, 10]
    assert [line.total_kopecks for line in a.lines] == [17580, 4500, 23997]

    assert (v.chain, v.is_complete, v.total_kopecks) == ("В", False, None)
    assert v.missing_product_ids == (BREAD,)
    assert [line.total_kopecks for line in v.lines] == [17000, None, 20700]


def test_result_does_not_depend_on_input_order() -> None:
    expected = chain_totals(BASKET, OFFERS, STORE_CHAINS)
    rng = random.Random(7)  # noqa: S311 (перемешивание для теста, не криптография)
    for _ in range(20):
        offers = rng.sample(OFFERS, len(OFFERS))
        stores = dict(rng.sample(list(STORE_CHAINS.items()), len(STORE_CHAINS)))
        assert chain_totals(BASKET, offers, stores) == expected


def test_only_requested_chains() -> None:
    only_b = {store: chain for store, chain in STORE_CHAINS.items() if chain == "Б"}
    assert [total.chain for total in chain_totals(BASKET, OFFERS, only_b)] == ["Б"]


class TestIncompleteBasket:
    """SCRUM-46: пропуски и покрытие, неполная корзина не обгоняет полную."""

    def test_cheaper_incomplete_basket_ranks_below_complete_ones(self) -> None:
        totals = chain_totals(BASKET, OFFERS, STORE_CHAINS)

        assert [total.chain for total in totals] == ["Б", "А", "В"]
        incomplete = totals[-1]
        # Без хлеба «В» выглядела бы дешевле всех: 377,00 ₽ против 453,90 ₽.
        assert incomplete.found_total_kopecks == 37700 < totals[0].found_total_kopecks

    def test_coverage(self) -> None:
        b, _, v = chain_totals(BASKET, OFFERS, STORE_CHAINS)
        assert (b.found_items_count, b.coverage_percent) == (3, 100)
        assert (v.found_items_count, v.coverage_percent) == (2, 66)  # 2/3 округляется вниз

    def test_coverage_of_incomplete_basket_never_shows_100(self) -> None:
        basket = [BasketItem(product_id, 1) for product_id in range(1, 31)]
        offers = [offer(product_id, 10, 100) for product_id in range(1, 30)]
        total = chain_totals(basket, offers, {10: "А"})[0]
        assert (total.found_items_count, total.coverage_percent) == (29, 96)

    def test_incomplete_chains_go_last_by_number_of_gaps(self) -> None:
        offers = [offer(MILK, 10, 100), offer(MILK, 20, 100), offer(BREAD, 10, 100)]
        offers.append(offer(PASTA, 10, 100))
        totals = chain_totals(BASKET, offers, {10: "А", 20: "Б", 30: "В"})
        assert [(t.chain, len(t.missing_product_ids)) for t in totals] == [
            ("А", 0),
            ("Б", 2),
            ("В", 3),
        ]


class TestPriceConditions:
    """SCRUM-47: контрольный пример из docs/planning.md."""

    OLD = NOW - timedelta(hours=30)
    BASKET: ClassVar = [BasketItem(MILK, 2), BasketItem(BREAD, 1), BasketItem(PASTA, 1)]

    def offers(self) -> list[ChainOffer]:
        return [
            offer(
                MILK,
                10,
                8000,
                price_type="promo",
                price_conditions="до 10.11",
                card_price_kopecks=7000,
            ),
            offer(BREAD, 10, 4000, is_fresh=False, observed_at=self.OLD),
            offer(PASTA, 10, 6000, in_stock=False),
        ]

    def test_card_price_is_shown_but_not_counted(self) -> None:
        total = chain_totals(self.BASKET, self.offers(), {10: "А"})[0]
        milk = total.lines[0]

        assert milk.total_kopecks == 16000  # 80,00 × 2, а не 70,00 × 2
        assert milk.offer is not None
        assert milk.offer.card_price_kopecks == 7000
        assert (milk.offer.price_type, milk.offer.price_conditions) == ("promo", "до 10.11")
        assert total.found_total_kopecks == 16000

    def test_stale_and_out_of_stock_prices_are_visible_but_not_counted(self) -> None:
        total = chain_totals(self.BASKET, self.offers(), {10: "А"})[0]
        _, bread, pasta = total.lines

        assert (bread.status, bread.total_kopecks) == (LineStatus.STALE, None)
        assert bread.offer is not None
        assert (bread.offer.price_kopecks, bread.offer.observed_at) == (4000, self.OLD)
        assert (pasta.status, pasta.total_kopecks) == (LineStatus.OUT_OF_STOCK, None)
        assert total.missing_product_ids == (BREAD, PASTA)
        assert total.oldest_observed_at == NOW

    def test_unknown_availability_is_not_confirmed(self) -> None:
        total = chain_totals(
            [BasketItem(MILK, 1)], [offer(MILK, 10, 100, in_stock=None)], {10: "А"}
        )
        assert total[0].lines[0].status is LineStatus.STOCK_UNKNOWN
        assert total[0].is_complete is False

    def test_not_sold(self) -> None:
        total = chain_totals([BasketItem(MILK, 1)], [], {10: "А"})[0]
        assert (total.lines[0].status, total.lines[0].offer) == (LineStatus.NOT_SOLD, None)
        assert total.oldest_observed_at is None

    def test_confirmed_price_beats_cheaper_stale_one(self) -> None:
        offers = [
            offer(MILK, 10, 5000, is_fresh=False, observed_at=self.OLD),
            offer(MILK, 11, 9000),
        ]
        line = chain_totals([BasketItem(MILK, 1)], offers, {10: "А", 11: "А"})[0].lines[0]
        assert line.offer is not None
        assert (line.offer.store_id, line.total_kopecks) == (11, 9000)

    def test_newest_stale_price_is_shown(self) -> None:
        offers = [
            offer(MILK, 10, 5000, is_fresh=False, observed_at=self.OLD),
            offer(MILK, 11, 6000, is_fresh=False, observed_at=self.OLD + timedelta(hours=1)),
        ]
        line = chain_totals([BasketItem(MILK, 1)], offers, {10: "А", 11: "А"})[0].lines[0]
        assert line.offer is not None
        assert line.offer.store_id == 11
