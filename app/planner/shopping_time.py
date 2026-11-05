"""Оценка времени покупок в одном магазине (F09).

    время = max(минимум визита,
                вход и касса + поиск позиций × коэффициент формата + пробивка упаковок)

- Вход и касса: зайти, взять корзину, отстоять очередь, оплатить, выйти (5 минут).
- Поиск позиций: дойти до полки и выбрать товар, около минуты на каждую разную позицию.
  В гипермаркете залы больше, поэтому дольше; в магазине у дома быстрее.
- Пробивка: выложить на ленту и пробить каждую упаковку, около 5 секунд.
- Минимум визита 10 минут. Небольшая покупка до 4 позиций всегда занимает 10 минут,
  ровно как в контрольном примере ТЗ (раздел 9.2): 1–2 позиции в магазине = 10 минут.

Все коэффициенты настраиваются через переменные окружения SHOPPING_*.
"""

from dataclasses import dataclass

STORE_FORMAT_SEARCH_PERCENT: dict[str, int] = {
    "convenience": 80,
    "supermarket": 100,
    "hypermarket": 140,
}


@dataclass(frozen=True)
class ShoppingTimeModel:
    min_visit_seconds: int = 600
    base_seconds: int = 300
    seconds_per_position: int = 60
    seconds_per_unit: int = 5

    def visit_seconds(self, positions: int, units: int, store_format: str = "supermarket") -> int:
        """Время в магазине: `positions` разных товаров, всего `units` упаковок."""
        search_percent = STORE_FORMAT_SEARCH_PERCENT.get(store_format, 100)
        search = self.seconds_per_position * positions * search_percent // 100
        estimate = self.base_seconds + search + self.seconds_per_unit * units
        return max(self.min_visit_seconds, estimate)
