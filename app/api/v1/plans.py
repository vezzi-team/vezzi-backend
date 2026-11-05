import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentUser, SessionDep, SettingsDep
from app.models import Plan, PlanItemStatus, PlanStatus
from app.schemas.common import error_responses
from app.schemas.planning import PlanItemUpdate, PlanRead, PlanSummary
from app.services import plans as plans_service

router = APIRouter(prefix="/plans", tags=["Планы покупки"], responses=error_responses(401, 404))


@router.get("")
def list_plans(
    user: CurrentUser,
    session: SessionDep,
    status_filter: Annotated[
        PlanStatus | None, Query(alias="status", description="Только планы с этим статусом")
    ] = None,
) -> list[PlanSummary]:
    """История планов пользователя, новые первыми (не больше 100)."""
    return [_summary(plan) for plan in plans_service.list_plans(session, user, status_filter)]


@router.get("/{plan_id}")
def get_plan(plan_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> PlanRead:
    """План целиком: магазины по порядку, позиции с отметками и линия маршрута."""
    return PlanRead.model_validate(plans_service.get_owned(session, user, plan_id))


@router.post("/{plan_id}/start", responses=error_responses(409))
def start_plan(
    plan_id: uuid.UUID, user: CurrentUser, session: SessionDep, settings: SettingsDep
) -> PlanRead:
    """Выбрать план и начать покупки: статус planned → active.

    Остальные варианты этого расчёта удаляются. Нельзя начать план, если цены
    в нём старше допустимого возраста или по корзине уже идёт другой план.
    """
    plan = plans_service.start(
        session, user, plan_id, datetime.now(UTC), settings.offer_max_age_hours
    )
    return PlanRead.model_validate(plan)


@router.patch("/{plan_id}/items/{item_id}", responses=error_responses(409, 422))
def update_plan_item(
    plan_id: uuid.UUID, item_id: int, body: PlanItemUpdate, user: CurrentUser, session: SessionDep
) -> PlanRead:
    """Отметить позицию в магазине: bought (куплено) или missing (нет на полке).

    Для missing в позиции уже указан запасной магазин этого маршрута, если он есть.
    """
    plan = plans_service.update_item(session, user, plan_id, item_id, body.status)
    return PlanRead.model_validate(plan)


@router.post("/{plan_id}/complete", responses=error_responses(409))
def complete_plan(plan_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> PlanRead:
    """Закончить покупки: план и его корзина получают статус completed."""
    plan = plans_service.complete(session, user, plan_id, datetime.now(UTC))
    return PlanRead.model_validate(plan)


@router.delete("/{plan_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_plan(plan_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> None:
    """Удалить план из истории."""
    plans_service.delete(session, user, plan_id)


def _summary(plan: Plan) -> PlanSummary:
    items = plan.items
    return PlanSummary(
        id=plan.id,
        cart_id=plan.cart_id,
        status=plan.status,
        total_kopecks=plan.total_kopecks,
        savings_kopecks=plan.savings_kopecks,
        stores_count=plan.stores_count,
        total_seconds=plan.total_seconds,
        items_count=len(items),
        bought_count=sum(1 for item in items if item.status is PlanItemStatus.BOUGHT),
        created_at=plan.created_at,
        started_at=plan.started_at,
        completed_at=plan.completed_at,
    )
