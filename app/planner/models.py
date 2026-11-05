"""Типы данных расчёта. Здесь нет ни базы данных, ни HTTP, только числа и идентификаторы."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final, Literal

START: Final = "start"
"""Метка стартовой точки пользователя в матрице пешего времени."""

type Place = int | Literal["start"]
"""Место на маршруте: id магазина или START."""


@dataclass(frozen=True)
class BasketItem:
    product_id: int
    quantity: int


@dataclass(frozen=True)
class Leg:
    """Пеший переход между двумя местами."""

    seconds: int
    meters: int


type TravelLegs = Mapping[tuple[Place, Place], Leg]
"""Матрица переходов. Отсутствующий ключ означает, что пешего пути нет."""

type PriceTable = Mapping[int, Mapping[int, int]]
"""product_id -> {store_id: цена упаковки в копейках}. Только свежие и доступные предложения."""
