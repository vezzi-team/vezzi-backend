"""Все модели импортируются здесь, чтобы Alembic видел полную схему БД."""

from app.models.auth import AuthIdentity, AuthProvider, RefreshSession
from app.models.cart import Cart, CartItem, CartStatus
from app.models.catalog import (
    CatalogImport,
    ImportStatus,
    Offer,
    PackageUnit,
    Product,
    Store,
    StoreFormat,
)
from app.models.plan import Plan, PlanItem, PlanItemStatus, PlanStatus, PlanStop
from app.models.user import User, UserRole

__all__ = [
    "AuthIdentity",
    "AuthProvider",
    "Cart",
    "CartItem",
    "CartStatus",
    "CatalogImport",
    "ImportStatus",
    "Offer",
    "PackageUnit",
    "Plan",
    "PlanItem",
    "PlanItemStatus",
    "PlanStatus",
    "PlanStop",
    "Product",
    "RefreshSession",
    "Store",
    "StoreFormat",
    "User",
    "UserRole",
]
