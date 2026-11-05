from fastapi import APIRouter

from app.api.v1 import admin, auth, carts, catalog, plans, users

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(catalog.router)
api_router.include_router(carts.router)
api_router.include_router(plans.router)
api_router.include_router(admin.router)
