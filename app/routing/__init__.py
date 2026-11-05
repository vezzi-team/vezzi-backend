from functools import lru_cache

from app.core.config import get_settings
from app.routing.base import (
    GeoPoint,
    NoRouteError,
    RoutingError,
    RoutingProvider,
    WalkingMatrix,
    WalkingRoute,
)
from app.routing.fake import FakeRoutingProvider
from app.routing.osrm import OsrmRoutingProvider

__all__ = [
    "GeoPoint",
    "NoRouteError",
    "RoutingError",
    "RoutingProvider",
    "WalkingMatrix",
    "WalkingRoute",
    "get_routing_provider",
]


@lru_cache
def get_routing_provider() -> RoutingProvider:
    """Провайдер выбирается настройкой ROUTING_PROVIDER и создаётся один раз на процесс."""
    settings = get_settings()
    match settings.routing_provider:
        case "osrm":
            return OsrmRoutingProvider(settings.osrm_base_url, settings.routing_timeout_seconds)
        case "fake":
            return FakeRoutingProvider()
