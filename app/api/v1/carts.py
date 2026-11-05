import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentUser, RoutingDep, SessionDep, SettingsDep
from app.models import CartStatus
from app.schemas.cart import (
    CartCreate,
    CartRead,
    CartSummary,
    CartUpdate,
    ItemAdd,
    ItemUpdate,
)
from app.schemas.common import error_responses
from app.schemas.comparison import ChainComparison
from app.schemas.planning import PlanRequest, PlanResponse
from app.services import carts as carts_service
from app.services import comparison, planning

router = APIRouter(prefix="/carts", tags=["Корзины"], responses=error_responses(401, 404))


@router.get("")
def list_carts(
    user: CurrentUser,
    session: SessionDep,
    status_filter: Annotated[
        CartStatus | None, Query(alias="status", description="Только корзины с этим статусом")
    ] = None,
) -> list[CartSummary]:
    """Корзины пользователя, недавно изменённые первыми."""
    return [
        CartSummary(
            id=cart.id,
            name=cart.name,
            status=cart.status,
            items_count=items_count,
            updated_at=cart.updated_at,
        )
        for cart, items_count in carts_service.list_summaries(session, user, status_filter)
    ]


@router.post("", status_code=status.HTTP_201_CREATED, responses=error_responses(422))
def create_cart(body: CartCreate, user: CurrentUser, session: SessionDep) -> CartRead:
    """Создать пустую корзину со статусом active."""
    return CartRead.model_validate(carts_service.create(session, user, body.name))


@router.get("/{cart_id}")
def get_cart(cart_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> CartRead:
    """Корзина с товарами. Чужая корзина недоступна: ответ 404."""
    return CartRead.model_validate(carts_service.get_owned(session, user, cart_id))


@router.patch("/{cart_id}", responses=error_responses(422))
def update_cart(
    cart_id: uuid.UUID, body: CartUpdate, user: CurrentUser, session: SessionDep
) -> CartRead:
    """Переименовать корзину или сменить её статус."""
    cart = carts_service.update(session, user, cart_id, name=body.name, status=body.status)
    return CartRead.model_validate(cart)


@router.delete("/{cart_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_cart(cart_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> None:
    """Удалить корзину вместе с позициями. Её планы остаются в истории."""
    carts_service.delete(session, user, cart_id)


@router.post("/{cart_id}/items", responses=error_responses(422))
def add_cart_item(
    cart_id: uuid.UUID, body: ItemAdd, user: CurrentUser, session: SessionDep
) -> CartRead:
    """Добавить товар. Если он уже в корзине, количество суммируется (не больше 99).

    В корзине может быть до 30 разных товаров (F03).
    """
    cart = carts_service.add_item(session, user, cart_id, body.product_id, body.quantity)
    return CartRead.model_validate(cart)


@router.patch("/{cart_id}/items/{product_id}", responses=error_responses(422))
def update_cart_item(
    cart_id: uuid.UUID, product_id: int, body: ItemUpdate, user: CurrentUser, session: SessionDep
) -> CartRead:
    """Задать новое количество товара (от 1 до 99)."""
    cart = carts_service.update_item(session, user, cart_id, product_id, body.quantity)
    return CartRead.model_validate(cart)


@router.delete("/{cart_id}/items/{product_id}")
def remove_cart_item(
    cart_id: uuid.UUID, product_id: int, user: CurrentUser, session: SessionDep
) -> CartRead:
    """Убрать товар из корзины."""
    return CartRead.model_validate(carts_service.remove_item(session, user, cart_id, product_id))


@router.post("/{cart_id}/plans", responses=error_responses(422, 503))
def calculate_plans(
    cart_id: uuid.UUID,
    body: PlanRequest,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
    routing: RoutingDep,
) -> PlanResponse:
    """Рассчитать до трёх планов покупки корзины с пешим маршрутом (F05–F11).

    Учитываются только свежие цены на товары в наличии. Планы отсортированы
    по цене, затем по общему времени и числу магазинов. Каждый план сохраняется
    со статусом planned: чтобы пойти по нему, вызовите `POST /plans/{plan_id}/start`.
    Новый расчёт заменяет невыбранные планы прошлого расчёта.
    Если план составить нельзя, приходит status = no_plans и объяснение в поле problem.
    """
    return planning.calculate_plans(
        session, settings, routing, user, cart_id, body, now=datetime.now(UTC)
    )


@router.get("/{cart_id}/chain-totals", responses=error_responses(422, 503))
def compare_chains(
    cart_id: uuid.UUID,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
    chain: Annotated[
        list[str] | None,
        Query(max_length=20, description="Только эти сети, можно повторять: ?chain=A&chain=B"),
    ] = None,
) -> ChainComparison:
    """Сколько стоит вся корзина в каждой сети: цена × количество по строкам и итог.

    Цена товара в сети: самая низкая свежая цена в наличии среди её магазинов.
    Итог есть только у сетей, где продаются все товары корзины. Всё в копейках, без округления.
    """
    return comparison.compare_chains(session, settings, user, cart_id, chain, now=datetime.now(UTC))
