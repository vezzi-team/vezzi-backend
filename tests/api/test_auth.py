from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from tests.conftest import PASSWORD

REGISTER = "/api/v1/auth/register"
LOGIN = "/api/v1/auth/login"
REFRESH = "/api/v1/auth/refresh"
LOGOUT = "/api/v1/auth/logout"
ME = "/api/v1/users/me"


def bearer(tokens: dict[str, str]) -> dict[str, str]:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def register_tokens(client: TestClient, email: str = "bob@example.com") -> dict[str, str]:
    response = client.post(REGISTER, json={"email": email, "password": PASSWORD})
    assert response.status_code == 201
    return response.json()["tokens"]


class TestRegistration:
    def test_returns_user_and_tokens(self, client: TestClient) -> None:
        response = client.post(REGISTER, json={"email": "Bob@Example.com", "password": PASSWORD})

        assert response.status_code == 201
        body = response.json()
        assert body["user"]["email"] == "bob@example.com"
        assert body["user"]["role"] == "user"
        assert body["tokens"]["token_type"] == "bearer"
        assert body["tokens"]["expires_in"] == 30 * 60

    def test_duplicate_email_is_rejected_case_insensitively(self, client: TestClient) -> None:
        register_tokens(client, "bob@example.com")
        response = client.post(REGISTER, json={"email": "BOB@example.com", "password": PASSWORD})
        assert response.status_code == 409
        assert response.json()["code"] == "email_taken"

    def test_short_password_gives_unified_validation_error(self, client: TestClient) -> None:
        response = client.post(REGISTER, json={"email": "bob@example.com", "password": "short"})

        assert response.status_code == 422
        body = response.json()
        assert body["code"] == "validation_error"
        assert body["request_id"] == response.headers["X-Request-ID"]
        assert body["details"][0]["field"] == "body.password"


class TestLogin:
    def test_login_with_correct_password(self, client: TestClient) -> None:
        register_tokens(client)
        response = client.post(LOGIN, json={"email": " BOB@example.com ", "password": PASSWORD})
        assert response.status_code == 200
        assert client.get(ME, headers=bearer(response.json()["tokens"])).status_code == 200

    @pytest.mark.parametrize("email", ["bob@example.com", "nobody@example.com"])
    def test_wrong_password_and_unknown_email_look_the_same(
        self, client: TestClient, email: str
    ) -> None:
        register_tokens(client)
        response = client.post(LOGIN, json={"email": email, "password": "wrong-password"})
        assert response.status_code == 401
        assert response.json()["code"] == "invalid_credentials"

    def test_rate_limit(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(get_settings(), "auth_rate_limit_per_minute", 3)
        statuses = [
            client.post(LOGIN, json={"email": "x@example.com", "password": "x"}).status_code
            for _ in range(4)
        ]
        assert statuses == [401, 401, 401, 429]


class TestAccessToken:
    def test_missing_token(self, client: TestClient) -> None:
        response = client.get(ME)
        assert response.status_code == 401
        assert response.json()["code"] == "not_authenticated"
        assert response.headers["WWW-Authenticate"] == "Bearer"

    def test_tampered_token(self, client: TestClient) -> None:
        tokens = register_tokens(client)
        response = client.get(ME, headers=bearer({"access_token": tokens["access_token"] + "x"}))
        assert response.status_code == 401
        assert response.json()["code"] == "invalid_token"

    def test_expired_token(self, client: TestClient) -> None:
        register_tokens(client)
        user_id = client.post(LOGIN, json={"email": "bob@example.com", "password": PASSWORD})
        user_id = user_id.json()["user"]["id"]
        past = datetime.now(UTC) - timedelta(hours=2)
        expired = jwt.encode(
            {"sub": user_id, "iat": past, "exp": past + timedelta(minutes=30)},
            get_settings().jwt_secret_key.get_secret_value(),
            algorithm="HS256",
        )
        assert client.get(ME, headers=bearer({"access_token": expired})).status_code == 401


class TestRefresh:
    def test_rotation_issues_new_pair(self, client: TestClient) -> None:
        tokens = register_tokens(client)
        response = client.post(REFRESH, json={"refresh_token": tokens["refresh_token"]})

        assert response.status_code == 200
        new_tokens = response.json()
        assert new_tokens["refresh_token"] != tokens["refresh_token"]
        assert client.get(ME, headers=bearer(new_tokens)).status_code == 200

    def test_reusing_old_token_revokes_the_whole_session(self, client: TestClient) -> None:
        tokens = register_tokens(client)
        rotated = client.post(REFRESH, json={"refresh_token": tokens["refresh_token"]}).json()

        reuse = client.post(REFRESH, json={"refresh_token": tokens["refresh_token"]})
        assert reuse.status_code == 401
        assert reuse.json()["code"] == "refresh_token_reused"

        after_reuse = client.post(REFRESH, json={"refresh_token": rotated["refresh_token"]})
        assert after_reuse.status_code == 401

    def test_unknown_token(self, client: TestClient) -> None:
        response = client.post(REFRESH, json={"refresh_token": "not-a-real-token"})
        assert response.status_code == 401
        assert response.json()["code"] == "invalid_refresh_token"

    def test_logout_revokes_refresh_token(self, client: TestClient) -> None:
        tokens = register_tokens(client)
        assert (
            client.post(LOGOUT, json={"refresh_token": tokens["refresh_token"]}).status_code == 204
        )
        assert (
            client.post(LOGOUT, json={"refresh_token": tokens["refresh_token"]}).status_code == 204
        )
        response = client.post(REFRESH, json={"refresh_token": tokens["refresh_token"]})
        assert response.status_code == 401

    def test_other_devices_are_not_logged_out(self, client: TestClient) -> None:
        phone = register_tokens(client)
        tablet = client.post(LOGIN, json={"email": "bob@example.com", "password": PASSWORD}).json()

        client.post(LOGOUT, json={"refresh_token": phone["refresh_token"]})
        response = client.post(REFRESH, json={"refresh_token": tablet["tokens"]["refresh_token"]})
        assert response.status_code == 200


class TestAccount:
    def test_change_password(self, client: TestClient) -> None:
        tokens = register_tokens(client)
        response = client.post(
            f"{ME}/password",
            headers=bearer(tokens),
            json={"current_password": PASSWORD, "new_password": "brand-new-password"},
        )
        assert response.status_code == 200

        old_session = client.post(REFRESH, json={"refresh_token": tokens["refresh_token"]})
        assert old_session.status_code == 401
        login = client.post(
            LOGIN, json={"email": "bob@example.com", "password": "brand-new-password"}
        )
        assert login.status_code == 200

    def test_change_password_requires_current_password(self, client: TestClient) -> None:
        tokens = register_tokens(client)
        response = client.post(
            f"{ME}/password",
            headers=bearer(tokens),
            json={"current_password": "wrong-password", "new_password": "brand-new-password"},
        )
        assert response.status_code == 400
        assert response.json()["code"] == "wrong_password"

    def test_delete_account_removes_user_and_carts(
        self, client: TestClient, register: Callable[[str], dict[str, str]]
    ) -> None:
        headers = register("carol@example.com")
        client.post("/api/v1/carts", headers=headers, json={"name": "Корзина"})

        assert client.delete(ME, headers=headers).status_code == 204
        assert client.get(ME, headers=headers).status_code == 401
        login = client.post(LOGIN, json={"email": "carol@example.com", "password": PASSWORD})
        assert login.status_code == 401
        assert (
            client.post(
                REGISTER, json={"email": "carol@example.com", "password": PASSWORD}
            ).status_code
            == 201
        )
