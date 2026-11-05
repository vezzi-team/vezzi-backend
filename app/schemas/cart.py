import uuid

from pydantic import Field, model_validator

from app.models.cart import CartStatus
from app.schemas.catalog import ProductRead
from app.schemas.common import Schema, Timestamp

MAX_ITEMS_PER_CART = 30
MAX_QUANTITY = 99


class CartCreate(Schema):
    name: str = Field(min_length=1, max_length=100, examples=["На неделю"])


class CartUpdate(Schema):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    status: CartStatus | None = Field(
        default=None,
        description="active: собираю сейчас, saved: отложена на потом, completed: всё куплено",
    )

    @model_validator(mode="after")
    def something_changes(self) -> "CartUpdate":
        if self.name is None and self.status is None:
            raise ValueError("Укажите name или status")
        return self


class ItemAdd(Schema):
    product_id: int
    quantity: int = Field(default=1, ge=1, le=MAX_QUANTITY)


class ItemUpdate(Schema):
    quantity: int = Field(ge=1, le=MAX_QUANTITY)


class CartItemRead(Schema):
    product: ProductRead
    quantity: int
    added_at: Timestamp


class CartSummary(Schema):
    id: uuid.UUID
    name: str
    status: CartStatus
    items_count: int
    updated_at: Timestamp


class CartRead(Schema):
    id: uuid.UUID
    name: str
    status: CartStatus
    items: list[CartItemRead]
    created_at: Timestamp
    updated_at: Timestamp
