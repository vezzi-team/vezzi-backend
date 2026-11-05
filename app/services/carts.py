"""Корзины (F01, F03). Каждый запрос проверяет, что корзина принадлежит пользователю."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.errors import BusinessRuleError, NotFoundError
from app.models import Cart, CartItem, CartStatus, Product, User
from app.schemas.cart import MAX_ITEMS_PER_CART, MAX_QUANTITY

MAX_CARTS_PER_USER = 50


def list_summaries(
    session: Session, user: User, status: CartStatus | None = None
) -> list[tuple[Cart, int]]:
    items_count = func.count(CartItem.product_id)
    statement = (
        select(Cart, items_count)
        .outerjoin(CartItem)
        .where(Cart.owner_id == user.id)
        .group_by(Cart.id)
        .order_by(Cart.updated_at.desc())
    )
    if status is not None:
        statement = statement.where(Cart.status == status)
    return [(cart, count) for cart, count in session.execute(statement)]


def get_owned(session: Session, user: User, cart_id: uuid.UUID) -> Cart:
    """Чужая корзина выглядит так же, как несуществующая: 404, а не 403.

    Так нельзя перебором узнать, какие идентификаторы корзин существуют.
    """
    cart = session.scalar(
        select(Cart)
        .options(selectinload(Cart.items))
        .where(Cart.id == cart_id, Cart.owner_id == user.id)
    )
    if cart is None:
        raise NotFoundError("Корзина не найдена", code="cart_not_found")
    return cart


def create(session: Session, user: User, name: str) -> Cart:
    count = session.scalar(select(func.count()).select_from(Cart).where(Cart.owner_id == user.id))
    if count is not None and count >= MAX_CARTS_PER_USER:
        raise BusinessRuleError(
            f"Можно хранить не больше {MAX_CARTS_PER_USER} корзин", code="too_many_carts"
        )
    cart = Cart(owner_id=user.id, name=name, status=CartStatus.ACTIVE, items=[])
    session.add(cart)
    session.commit()
    return cart


def update(
    session: Session,
    user: User,
    cart_id: uuid.UUID,
    name: str | None = None,
    status: CartStatus | None = None,
) -> Cart:
    cart = get_owned(session, user, cart_id)
    if name is not None:
        cart.name = name
    if status is not None:
        cart.status = status
    session.commit()
    return cart


def delete(session: Session, user: User, cart_id: uuid.UUID) -> None:
    """Удаляет корзину. Её планы остаются в истории без ссылки на корзину."""
    session.delete(get_owned(session, user, cart_id))
    session.commit()


def add_item(
    session: Session, user: User, cart_id: uuid.UUID, product_id: int, quantity: int
) -> Cart:
    """Добавляет товар. Если он уже есть, количества складываются (F03)."""
    cart = get_owned(session, user, cart_id)
    if session.get(Product, product_id) is None:
        raise NotFoundError("Товар не найден", code="product_not_found")

    existing = _find_item(cart, product_id)
    if existing is not None:
        new_quantity = existing.quantity + quantity
        if new_quantity > MAX_QUANTITY:
            raise BusinessRuleError(
                f"Количество одного товара не может быть больше {MAX_QUANTITY}",
                code="quantity_limit_exceeded",
            )
        existing.quantity = new_quantity
    else:
        if len(cart.items) >= MAX_ITEMS_PER_CART:
            raise BusinessRuleError(
                f"В корзине может быть не больше {MAX_ITEMS_PER_CART} разных товаров",
                code="items_limit_exceeded",
            )
        cart.items.append(CartItem(product_id=product_id, quantity=quantity))

    _touch(cart)
    session.commit()
    return cart


def update_item(
    session: Session, user: User, cart_id: uuid.UUID, product_id: int, quantity: int
) -> Cart:
    cart = get_owned(session, user, cart_id)
    _require_item(cart, product_id).quantity = quantity
    _touch(cart)
    session.commit()
    return cart


def remove_item(session: Session, user: User, cart_id: uuid.UUID, product_id: int) -> Cart:
    cart = get_owned(session, user, cart_id)
    cart.items.remove(_require_item(cart, product_id))
    _touch(cart)
    session.commit()
    return cart


def _find_item(cart: Cart, product_id: int) -> CartItem | None:
    return next((item for item in cart.items if item.product_id == product_id), None)


def _require_item(cart: Cart, product_id: int) -> CartItem:
    item = _find_item(cart, product_id)
    if item is None:
        raise NotFoundError("Этого товара нет в корзине", code="item_not_found")
    return item


def _touch(cart: Cart) -> None:
    """Изменение позиций тоже считается изменением корзины."""
    cart.updated_at = datetime.now(UTC)
