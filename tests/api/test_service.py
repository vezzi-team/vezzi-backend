import re
from collections.abc import Callable

from fastapi.testclient import TestClient

from app import __version__
from app.catalog_import.publisher import ImportReport


def test_health_and_ready(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/ready").json() == {"status": "ok", "database": "ok"}


def test_version_shows_build(client: TestClient) -> None:
    assert client.get("/version").json() == {"version": __version__, "commit": "dev"}


def test_unknown_route_uses_unified_error_format(client: TestClient) -> None:
    response = client.get("/api/v1/nope")
    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "not_found"
    assert body["message"] == "Такого адреса нет"
    assert body["request_id"] == response.headers["X-Request-ID"]


def test_wrong_method(client: TestClient) -> None:
    response = client.put("/health")
    assert response.status_code == 405
    assert response.json()["code"] == "method_not_allowed"
    assert response.json()["message"] == "Этот адрес не принимает такой запрос"


def test_json_responses_declare_utf8(client: TestClient) -> None:
    for path in ["/health", "/api/v1/users/me", "/openapi.json"]:
        response = client.get(path)
        assert response.headers["content-type"] == "application/json; charset=utf-8", path
    assert client.get("/api/v1/users/me").json()["message"] == "Требуется вход в аккаунт"


def test_incoming_request_id_is_kept(client: TestClient) -> None:
    response = client.get("/health", headers={"X-Request-ID": "ios-1234567890"})
    assert response.headers["X-Request-ID"] == "ios-1234567890"


def test_swagger_is_available(client: TestClient) -> None:
    assert client.get("/docs").status_code == 200
    schema = client.get("/openapi.json").json()
    assert schema["info"]["title"] == "Vezzi API"
    assert "HTTPBearer" in schema["components"]["securitySchemes"]


def test_timestamps_have_no_fractional_seconds(
    client: TestClient, register: Callable[[str], dict[str, str]], demo_catalog: ImportReport
) -> None:
    """Swift-декодер `.iso8601` не принимает доли секунды, поэтому сервер их не отдаёт."""
    headers = register("swift@example.com")
    created_at = client.get("/api/v1/users/me", headers=headers).json()["created_at"]
    imported_at = client.get("/api/v1/catalog", headers=headers).json()["imported_at"]
    for value in (created_at, imported_at):
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", value), value
