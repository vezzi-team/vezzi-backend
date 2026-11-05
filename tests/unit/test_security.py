import uuid

import pytest

from app.core.config import Settings
from app.core.security import (
    InvalidTokenError,
    create_access_token,
    decode_access_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)

SETTINGS = Settings(jwt_secret_key="unit-test-secret-key-long-enough-for-hs256")


def test_password_hash_is_salted_argon2() -> None:
    first, second = hash_password("secret-password"), hash_password("secret-password")
    assert first.startswith("$argon2id$")
    assert first != second
    assert verify_password("secret-password", first)
    assert not verify_password("other-password", first)


def test_account_without_password_never_matches() -> None:
    assert verify_password("anything", None) is False


def test_access_token_roundtrip() -> None:
    user_id = uuid.uuid4()
    token = create_access_token(user_id, SETTINGS)
    assert decode_access_token(token.token, SETTINGS) == user_id
    assert token.expires_in == SETTINGS.access_token_ttl_minutes * 60


def test_token_signed_with_other_key_is_rejected() -> None:
    other = Settings(jwt_secret_key="another-secret-key-also-long-enough-xx")
    token = create_access_token(uuid.uuid4(), other)
    with pytest.raises(InvalidTokenError):
        decode_access_token(token.token, SETTINGS)


def test_refresh_token_is_stored_as_sha256() -> None:
    assert len(hash_refresh_token("token")) == 64
    assert hash_refresh_token("token") == hash_refresh_token("token")


def test_production_rejects_unsafe_settings() -> None:
    with pytest.raises(ValueError, match="JWT_SECRET_KEY"):
        Settings(environment="production", jwt_secret_key="short", routing_provider="osrm")
    with pytest.raises(ValueError, match="JWT_SECRET_KEY"):
        Settings(
            environment="production",
            jwt_secret_key="change-me-in-env-file-at-least-32-chars",
            routing_provider="osrm",
        )
    with pytest.raises(ValueError, match="fake"):
        Settings(environment="production", jwt_secret_key="x" * 40, routing_provider="fake")
