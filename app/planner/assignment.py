"""Распределение товаров по магазинам внутри выбранного набора магазинов (F07)."""

from collections.abc import Collection, Sequence
from dataclasses import dataclass

from app.planner.models import BasketItem, PriceTable


@dataclass(frozen=True)
class AssignedItem:
    product_id: int
    quantity: int
    store_id: int
    unit_price_kopecks: int

    @property
    def total_kopecks(self) -> int:
        return self.unit_price_kopecks * self.quantity


def assign_cheapest(
    basket: Sequence[BasketItem], prices: PriceTable, stores: Collection[int]
) -> list[AssignedItem] | None:
    """Каждый товар берём там, где он дешевле всего среди `stores`.

    При равной цене выигрывает магазин с меньшим id, поэтому результат всегда
    одинаковый. Если хотя бы один товар нигде не продаётся, корзина неполная
    и функция возвращает None: неполную корзину нельзя выдавать как план.
    """
    assigned = []
    for item in basket:
        offers = prices.get(item.product_id, {})
        candidates = [(price, store_id) for store_id, price in offers.items() if store_id in stores]
        if not candidates:
            return None
        price, store_id = min(candidates)
        assigned.append(AssignedItem(item.product_id, item.quantity, store_id, price))
    return assigned


def cheapest_alternative(
    product_id: int, prices: PriceTable, stores: Collection[int], chosen_store: int
) -> tuple[int, int] | None:
    """Запасной вариант для товара: самый дешёвый другой магазин из `stores`.

    Нужен в магазине, когда товара не оказалось на полке: пользователь сразу видит,
    где ещё на этом же маршруте его можно купить. Возвращает (store_id, цена) или None.
    """
    offers = prices.get(product_id, {})
    candidates = [
        (price, store_id)
        for store_id, price in offers.items()
        if store_id in stores and store_id != chosen_store
    ]
    if not candidates:
        return None
    price, store_id = min(candidates)
    return store_id, price
