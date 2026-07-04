"""Tests for the Supabase bearer-token authentication boundary."""

from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace
import threading
from unittest.mock import MagicMock

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from jwt.exceptions import PyJWKClientConnectionError

import backend.auth as auth
from backend.auth import (
    SupabaseTokenVerifier,
    TokenVerificationError,
    _synchronize_user,
    get_token_verifier,
    router,
)
from backend.config import settings
from backend.database import Base, User, get_db


class StubTokenVerifier:
    def __init__(self, identity: dict | None = None, error: Exception | None = None):
        self.identity = identity
        self.error = error
        self.tokens: list[str] = []

    def verify(self, token: str) -> dict:
        self.thread_id = threading.get_ident()
        self.tokens.append(token)
        if self.error:
            raise self.error
        assert self.identity is not None
        return self.identity


@pytest.fixture
def db_session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def app(db_session: Session) -> FastAPI:
    application = FastAPI()

    @application.middleware("http")
    async def record_event_loop_thread(request, call_next):
        application.state.event_loop_thread_id = threading.get_ident()
        return await call_next(request)

    application.include_router(router)

    def override_db():
        yield db_session

    application.dependency_overrides[get_db] = override_db
    return application


@pytest.fixture
def trial_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "DEPLOYMENT_MODE", "trial")
    monkeypatch.setattr(settings, "DISABLE_AUTH", False)


def verified_identity(**overrides) -> dict:
    identity = {
        "sub": "user-123",
        "email": "person@example.com",
        "name": "Person Example",
        "role": "authenticated",
        "email_confirmed_at": "2026-07-04T12:00:00Z",
    }
    identity.update(overrides)
    return identity


class StubResponse:
    def __init__(self, payload, status_code: int = 200):
        self.payload = payload
        self.status_code = status_code

    def json(self):
        return self.payload


class StubHttpClient:
    def __init__(self, response=None, error: Exception | None = None):
        self.response = response
        self.error = error

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def get(self, *args, **kwargs):
        if self.error:
            raise self.error
        return self.response


class StubJwksClient:
    def __init__(self, key):
        self.key = key

    def get_signing_key_from_jwt(self, token: str):
        return SimpleNamespace(key=self.key)


def build_verifier(response=None, error: Exception | None = None):
    client = StubHttpClient(response=response, error=error)
    verifier = SupabaseTokenVerifier(
        "https://project.supabase.co",
        "publishable-key",
        http_client_factory=lambda **kwargs: client,
    )
    verifier._verify_jwt = lambda token: {
        "sub": "user-123",
        "role": "authenticated",
    }
    return verifier


def signed_token(**claim_overrides) -> tuple[str, object]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    claims = {
        "sub": "user-123",
        "iss": "https://project.supabase.co/auth/v1",
        "aud": "authenticated",
        "role": "authenticated",
        "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
    }
    claims.update(claim_overrides)
    token = jwt.encode(claims, private_key, algorithm="RS256")
    return token, private_key.public_key()


def test_trial_mode_rejects_missing_bearer_token(
    app: FastAPI, trial_mode: None
) -> None:
    verifier = StubTokenVerifier(identity=verified_identity())
    app.dependency_overrides[get_token_verifier] = lambda: verifier

    response = TestClient(app).get("/auth/me")

    assert response.status_code == 401
    assert verifier.tokens == []


def test_trial_mode_rejects_invalid_bearer_token(
    app: FastAPI, trial_mode: None
) -> None:
    verifier = StubTokenVerifier(error=TokenVerificationError("invalid token"))
    app.dependency_overrides[get_token_verifier] = lambda: verifier

    response = TestClient(app).get(
        "/auth/me", headers={"Authorization": "Bearer invalid-token"}
    )

    assert response.status_code == 401
    assert verifier.tokens == ["invalid-token"]


def test_trial_mode_accepts_verified_identity_and_synchronizes_user(
    app: FastAPI, db_session: Session, trial_mode: None
) -> None:
    db_session.add(
        User(id="user-123", email="old@example.com", name="Old Name")
    )
    db_session.commit()
    verifier = StubTokenVerifier(identity=verified_identity())
    app.dependency_overrides[get_token_verifier] = lambda: verifier

    response = TestClient(app).get(
        "/auth/me", headers={"Authorization": "Bearer verified-token"}
    )

    assert response.status_code == 200
    assert response.json() == {
        "authenticated": True,
        "id": "user-123",
        "name": "Person Example",
        "email": "person@example.com",
        "created_at": response.json()["created_at"],
    }
    synchronized = db_session.get(User, "user-123")
    assert synchronized.email == "person@example.com"
    assert synchronized.name == "Person Example"
    assert verifier.tokens == ["verified-token"]


def test_trial_mode_rejects_identity_with_unverified_email(
    app: FastAPI, trial_mode: None
) -> None:
    verifier = StubTokenVerifier(
        identity=verified_identity(email_confirmed_at=None)
    )
    app.dependency_overrides[get_token_verifier] = lambda: verifier

    response = TestClient(app).get(
        "/auth/me", headers={"Authorization": "Bearer unverified-token"}
    )

    assert response.status_code == 403


def test_testing_mode_uses_development_identity_without_bearer_token(
    app: FastAPI, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "DEPLOYMENT_MODE", "testing")
    verifier = StubTokenVerifier(error=AssertionError("verifier must not be called"))
    app.dependency_overrides[get_token_verifier] = lambda: verifier

    response = TestClient(app).get("/auth/me")

    assert response.status_code == 200
    assert response.json()["id"] == "dev_user_001"
    assert response.json()["email"] == "dev@accesspdf.local"
    assert db_session.get(User, "dev_user_001") is not None
    assert verifier.tokens == []


def test_production_verifier_is_cached_and_uses_short_jwks_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "SUPABASE_URL", "https://project.supabase.co")
    monkeypatch.setattr(settings, "SUPABASE_PUBLISHABLE_KEY", "publishable-key")
    get_token_verifier.cache_clear()

    first = get_token_verifier()
    second = get_token_verifier()

    assert first is second
    assert first.jwks_client.timeout == 5
    get_token_verifier.cache_clear()


def test_valid_rs256_token_enforces_expected_supabase_claims() -> None:
    verifier = SupabaseTokenVerifier(
        "https://project.supabase.co", "publishable-key"
    )
    token, public_key = signed_token()
    verifier.jwks_client = StubJwksClient(public_key)

    claims = verifier._verify_jwt(token)

    assert claims["sub"] == "user-123"


@pytest.mark.parametrize(
    "claim_overrides",
    [
        {"iss": "https://attacker.example/auth/v1"},
        {"aud": "anon"},
        {"role": "anon"},
        {"exp": datetime.now(timezone.utc) - timedelta(minutes=1)},
    ],
)
def test_jwt_claim_mismatch_is_a_credential_error(claim_overrides: dict) -> None:
    verifier = SupabaseTokenVerifier(
        "https://project.supabase.co", "publishable-key"
    )
    token, public_key = signed_token(**claim_overrides)
    verifier.jwks_client = StubJwksClient(public_key)

    with pytest.raises(TokenVerificationError):
        verifier._verify_jwt(token)


def test_disallowed_jwt_algorithm_is_a_credential_error() -> None:
    verifier = SupabaseTokenVerifier(
        "https://project.supabase.co", "publishable-key"
    )
    token = jwt.encode(
        {
            "sub": "user-123",
            "iss": verifier.issuer,
            "aud": "authenticated",
            "role": "authenticated",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        },
        "not-a-public-key",
        algorithm="HS256",
    )
    verifier.jwks_client = StubJwksClient("not-a-public-key")

    with pytest.raises(TokenVerificationError):
        verifier._verify_jwt(token)


def test_subject_mismatch_is_a_credential_error() -> None:
    verifier = build_verifier(
        StubResponse(
            {
                "id": "different-user",
                "email": "person@example.com",
                "email_confirmed_at": "2026-07-04T12:00:00Z",
                "user_metadata": {},
            }
        )
    )

    with pytest.raises(TokenVerificationError):
        verifier.verify("token")


@pytest.mark.parametrize(
    "payload",
    [
        ["not", "an", "object"],
        {
            "id": "user-123",
            "email": "person@example.com",
            "email_confirmed_at": "2026-07-04T12:00:00Z",
            "user_metadata": ["not", "an", "object"],
        },
    ],
)
def test_malformed_user_response_is_provider_unavailable(payload) -> None:
    verifier = build_verifier(StubResponse(payload))

    with pytest.raises(auth.AuthProviderUnavailableError):
        verifier.verify("token")


def test_auth_provider_timeout_is_provider_unavailable() -> None:
    verifier = build_verifier(
        error=httpx.ReadTimeout("provider timed out")
    )

    with pytest.raises(auth.AuthProviderUnavailableError):
        verifier.verify("token")


def test_jwks_network_failure_is_provider_unavailable() -> None:
    verifier = SupabaseTokenVerifier(
        "https://project.supabase.co", "publishable-key"
    )
    verifier.jwks_client = MagicMock()
    verifier.jwks_client.get_signing_key_from_jwt.side_effect = (
        PyJWKClientConnectionError("JWKS detail")
    )

    with pytest.raises(auth.AuthProviderUnavailableError):
        verifier._verify_jwt("token")


def test_malformed_jwks_json_maps_to_generic_503(
    app: FastAPI, trial_mode: None
) -> None:
    verifier = SupabaseTokenVerifier(
        "https://project.supabase.co", "publishable-key"
    )
    verifier.jwks_client = MagicMock()
    verifier.jwks_client.get_signing_key_from_jwt.side_effect = (
        json.JSONDecodeError("malformed JWKS internal detail", "", 0)
    )
    app.dependency_overrides[get_token_verifier] = lambda: verifier

    response = TestClient(app, raise_server_exceptions=False).get(
        "/auth/me", headers={"Authorization": "Bearer malformed-jwks-token"}
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "Authentication service unavailable"}
    assert "malformed JWKS internal detail" not in response.text


def test_malformed_jwks_json_is_typed_as_provider_unavailable() -> None:
    verifier = SupabaseTokenVerifier(
        "https://project.supabase.co", "publishable-key"
    )
    verifier.jwks_client = MagicMock()
    verifier.jwks_client.get_signing_key_from_jwt.side_effect = (
        json.JSONDecodeError("malformed JWKS internal detail", "", 0)
    )

    with pytest.raises(auth.AuthProviderUnavailableError):
        verifier._verify_jwt("malformed-jwks-token")


def test_user_lookup_uses_short_explicit_timeout() -> None:
    captured: dict = {}
    client = StubHttpClient(
        response=StubResponse(
            {
                "id": "user-123",
                "email": "person@example.com",
                "email_confirmed_at": "2026-07-04T12:00:00Z",
                "user_metadata": {},
            }
        )
    )

    def client_factory(**kwargs):
        captured.update(kwargs)
        return client

    verifier = SupabaseTokenVerifier(
        "https://project.supabase.co",
        "publishable-key",
        http_client_factory=client_factory,
    )
    verifier._verify_jwt = lambda token: {
        "sub": "user-123",
        "role": "authenticated",
    }

    verifier.verify("token")

    assert captured["timeout"] == 5.0


def test_trial_mode_maps_provider_unavailable_to_503(
    app: FastAPI, trial_mode: None
) -> None:
    verifier = StubTokenVerifier(
        error=auth.AuthProviderUnavailableError("provider detail")
    )
    app.dependency_overrides[get_token_verifier] = lambda: verifier

    response = TestClient(app).get(
        "/auth/me", headers={"Authorization": "Bearer unavailable-token"}
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "Authentication service unavailable"}
    assert "provider detail" not in response.text


def test_trial_verifier_runs_outside_request_event_loop(
    app: FastAPI, trial_mode: None
) -> None:
    verifier = StubTokenVerifier(identity=verified_identity())
    app.dependency_overrides[get_token_verifier] = lambda: verifier

    response = TestClient(app).get(
        "/auth/me", headers={"Authorization": "Bearer verified-token"}
    )

    assert response.status_code == 200
    assert verifier.thread_id != app.state.event_loop_thread_id


def test_user_synchronization_recovers_from_concurrent_insert() -> None:
    concurrent_user = User(
        id="user-123", email="person@example.com", name="Concurrent Name"
    )
    db = MagicMock(spec=Session)
    db.get.side_effect = [None, concurrent_user]
    db.commit.side_effect = [
        IntegrityError("insert", {}, Exception("duplicate")),
        None,
    ]

    result = _synchronize_user(db, verified_identity())

    assert result is concurrent_user
    db.rollback.assert_called_once_with()
    assert db.get.call_count == 2
    assert db.commit.call_count == 2
    assert concurrent_user.name == "Person Example"


def test_user_synchronization_rejects_email_owned_by_another_subject(
    db_session: Session,
) -> None:
    db_session.add(
        User(id="other-user", email="person@example.com", name="Other User")
    )
    db_session.commit()

    with pytest.raises(auth.UserSynchronizationError):
        _synchronize_user(db_session, verified_identity())

    assert db_session.get(User, "other-user") is not None
