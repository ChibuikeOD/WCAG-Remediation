"""Tests for the Supabase bearer-token authentication boundary."""

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.auth import TokenVerificationError, get_token_verifier, router
from backend.config import settings
from backend.database import Base, User, get_db


class StubTokenVerifier:
    def __init__(self, identity: dict | None = None, error: Exception | None = None):
        self.identity = identity
        self.error = error
        self.tokens: list[str] = []

    async def verify(self, token: str) -> dict:
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
