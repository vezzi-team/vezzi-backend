import uuid
from typing import Literal

from pydantic import Field

from app.models.plan import PlanItemStatus, PlanStatus
from app.planner.optimizer import PlanningProblem
from app.schemas.catalog import ProductRead, StoreRead
from app.schemas.common import Coordinates, Schema, Timestamp


class Substitution(Schema):
    """Замена, которую пользователь явно подтвердил (F10)."""

    product_id: int = Field(description="Товар из корзины")
    replacement_product_id: int = Field(description="Аналог, которым его заменяем")


class PlanRequest(Schema):
    start: Coordinates = Field(description="Откуда пользователь начинает маршрут")
    max_stores: int = Field(default=3, ge=1, le=5, description="Сколько магазинов готов обойти")
    max_total_minutes: int = Field(
        default=60, ge=10, le=180, description="Лимит общего времени: дорога и покупки"
    )
    substitutions: list[Substitution] = Field(default_factory=list, max_length=30)
    store_ids: list[int] | None = Field(
        default=None,
        min_length=1,
        max_length=15,
        description="Рассматривать только эти магазины. Если не задано, берём ближайшие",
    )
    radius_meters: int | None = Field(
        default=None,
        ge=100,
        le=5000,
        description=(
            "Радиус круга на карте вокруг старта: магазины дальше этого расстояния по прямой "
            "не рассматриваются. Если не задан, ограничения нет"
        ),
    )


class PlanItemRead(Schema):
    id: int
    product: ProductRead
    quantity: int
    unit_price_kopecks: int
    total_kopecks: int
    card_price_kopecks: int | None = Field(description="Цена по карте. В итог плана не входит")
    price_type: str | None
    price_conditions: str | None
    price_updated_at: Timestamp
    status: PlanItemStatus = Field(
        description="planned: ещё не куплен, bought: куплен, missing: не оказалось в магазине"
    )
    alternative_store_id: int | None = Field(
        description="Другой магазин этого маршрута, где товар тоже есть (на случай missing)"
    )
    alternative_price_kopecks: int | None


class PlanStopRead(Schema):
    position: int = Field(description="Номер магазина в маршруте, начиная с 1")
    store: StoreRead
    items: list[PlanItemRead]
    subtotal_kopecks: int
    shopping_seconds: int
    walk_from_previous_seconds: int = Field(description="Путь от старта или предыдущего магазина")
    walk_from_previous_meters: int


class RouteGeometry(Schema):
    provider: str = Field(examples=["osrm"])
    uses_road_network: bool = Field(
        description="false: линия построена по прямой (тестовый режим), это не настоящий маршрут"
    )
    points: list[Coordinates] = Field(description="Линия маршрута от старта до последнего магазина")


class PlanRead(Schema):
    id: uuid.UUID
    cart_id: uuid.UUID | None = Field(description="null, если корзину уже удалили")
    status: PlanStatus = Field(
        description="planned: рассчитан, active: идут покупки, completed: завершён"
    )
    rank: int = Field(description="Место среди вариантов расчёта, 1 = лучший")
    total_kopecks: int
    savings_kopecks: int | None = Field(
        description="Экономия к лучшему плану в одном магазине; null, если сравнивать не с чем"
    )
    stores_count: int
    walking_seconds: int
    walking_meters: int
    shopping_seconds: int
    total_seconds: int
    stops: list[PlanStopRead]
    route: RouteGeometry
    data_is_synthetic: bool
    created_at: Timestamp
    started_at: Timestamp | None
    completed_at: Timestamp | None


class PlanSummary(Schema):
    """Строка истории планов, без маршрута и позиций."""

    id: uuid.UUID
    cart_id: uuid.UUID | None
    status: PlanStatus
    total_kopecks: int
    savings_kopecks: int | None
    stores_count: int
    total_seconds: int
    items_count: int
    bought_count: int
    created_at: Timestamp
    started_at: Timestamp | None
    completed_at: Timestamp | None


class PlanItemUpdate(Schema):
    status: PlanItemStatus


class Baseline(Schema):
    store: StoreRead
    total_kopecks: int


class PlanProblem(Schema):
    reason: PlanningProblem
    message: str
    unavailable_products: list[ProductRead] = Field(default_factory=list)
    min_required_stores: int | None = None
    min_required_minutes: int | None = None
    min_required_radius_meters: int | None = Field(
        default=None, description="Для radius_too_small: при каком радиусе продаются все товары"
    )


class PlanResponse(Schema):
    status: Literal["ok", "no_plans"]
    plans: list[PlanRead] = Field(description="До трёх полных планов, лучший первым")
    baseline: Baseline | None = Field(description="Самый дешёвый допустимый план в одном магазине")
    problem: PlanProblem | None = Field(description="Почему не удалось составить план")
    calculated_at: Timestamp
    offer_max_age_hours: int
    data_is_synthetic: bool
