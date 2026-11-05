"""Сохранённые планы: история, выбор плана и отметки во время покупок (D01).

Статусы плана: planned → active → completed.
- Расчёт создаёт до трёх планов planned и заменяет прошлые planned этой корзины.
- start: пользователь выбрал план, остальные варианты этого расчёта удаляются.
- update_item: отметка «куплено» или «нет в магазине».
- complete: покупки закончены, корзина получает статус completed.
"""

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import delete as sql_delete
from sqlalchemy import exists, select
from sqlalchemy.orm import Session, selectinload

from app.core.errors import ConflictError, NotFoundError
from app.models import Cart, CartStatus, Plan, PlanItemStatus, PlanStatus, PlanStop, User
from app.services.catalog import freshness_cutoff

MAX_PLANS_IN_HISTORY = 100
# План почти всегда нужен целиком: с магазинами и позициями.
_WITH_CONTENTS = selectinload(Plan.stops).selectinload(PlanStop.items)


def list_plans(session: Session, user: User, status: PlanStatus | None = None) -> list[Plan]:
    statement = (
        select(Plan)
        .options(_WITH_CONTENTS)
        .where(Plan.owner_id == user.id)
        .order_by(Plan.created_at.desc(), Plan.rank)
        .limit(MAX_PLANS_IN_HISTORY)
    )
    if status is not None:
        statement = statement.where(Plan.status == status)
    return list(session.scalars(statement))


def get_owned(session: Session, user: User, plan_id: uuid.UUID) -> Plan:
    plan = session.scalar(
        select(Plan).options(_WITH_CONTENTS).where(Plan.id == plan_id, Plan.owner_id == user.id)
    )
    if plan is None:
        raise NotFoundError("План не найден", code="plan_not_found")
    return plan


def replace_proposals(session: Session, cart: Cart, plans: Sequence[Plan]) -> None:
    """Сохраняет новые варианты расчёта вместо прошлых невыбранных."""
    session.execute(
        sql_delete(Plan).where(Plan.cart_id == cart.id, Plan.status == PlanStatus.PLANNED)
    )
    session.add_all(plans)
    session.commit()


def start(
    session: Session, user: User, plan_id: uuid.UUID, now: datetime, max_age_hours: int
) -> Plan:
    plan = get_owned(session, user, plan_id)
    if plan.status is not PlanStatus.PLANNED:
        raise ConflictError("Этот план уже выбран", code="plan_already_started")
    if plan.created_at < freshness_cutoff(now, max_age_hours):
        raise ConflictError("Цены в плане устарели, рассчитайте заново", code="plan_expired")
    if plan.cart_id is not None and _has_active_plan(session, plan.cart_id):
        raise ConflictError(
            "По этой корзине уже идут покупки. Завершите или удалите начатый план",
            code="active_plan_exists",
        )

    plan.status = PlanStatus.ACTIVE
    plan.started_at = now
    if plan.cart_id is not None:
        session.execute(
            sql_delete(Plan).where(
                Plan.cart_id == plan.cart_id,
                Plan.status == PlanStatus.PLANNED,
                Plan.id != plan.id,
            )
        )
    session.commit()
    return plan


def update_item(
    session: Session, user: User, plan_id: uuid.UUID, item_id: int, status: PlanItemStatus
) -> Plan:
    plan = _get_active(session, user, plan_id)
    item = next((item for item in plan.items if item.id == item_id), None)
    if item is None:
        raise NotFoundError("Такой позиции в плане нет", code="plan_item_not_found")
    item.status = status
    session.commit()
    return plan


def complete(session: Session, user: User, plan_id: uuid.UUID, now: datetime) -> Plan:
    plan = _get_active(session, user, plan_id)
    plan.status = PlanStatus.COMPLETED
    plan.completed_at = now
    if plan.cart is not None:
        plan.cart.status = CartStatus.COMPLETED
    session.commit()
    return plan


def delete(session: Session, user: User, plan_id: uuid.UUID) -> None:
    session.delete(get_owned(session, user, plan_id))
    session.commit()


def _get_active(session: Session, user: User, plan_id: uuid.UUID) -> Plan:
    plan = get_owned(session, user, plan_id)
    if plan.status is not PlanStatus.ACTIVE:
        raise ConflictError(
            "Отмечать покупки и завершать можно только начатый план", code="plan_not_active"
        )
    return plan


def _has_active_plan(session: Session, cart_id: uuid.UUID) -> bool:
    active = exists().where(Plan.cart_id == cart_id, Plan.status == PlanStatus.ACTIVE)
    return bool(session.scalar(select(active)))
