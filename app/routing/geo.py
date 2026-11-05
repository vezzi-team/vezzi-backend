import math

from app.routing.base import GeoPoint

EARTH_RADIUS_METERS = 6_371_000


def haversine_meters(a: GeoPoint, b: GeoPoint) -> float:
    """Расстояние по прямой между двумя точками на поверхности Земли."""
    lat1, lon1, lat2, lon2 = map(math.radians, (a.latitude, a.longitude, b.latitude, b.longitude))
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * EARTH_RADIUS_METERS * math.asin(math.sqrt(h))
