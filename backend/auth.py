"""Supabase bearer authentication for trial deployments."""

import logging
from collections.abc import Callable
from functools import lru_cache
from typing import Protocol

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient
from jwt.exceptions import PyJWKClientConnectionError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import settings
from .database import User, get_db


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["Authentication"])
bearer_scheme = HTTPBearer(auto_error=False)

ALLOWED_ALGORITHMS = ["RS256", "ES256"]


class TokenVerificationError(Exception):
    """Raised when a bearer token cannot establish a trusted identity."""


class AuthProviderUnavailableError(Exception):
    """Raised when Supabase cannot provide a trustworthy auth response."""


class UserSynchronizationError(Exception):
    """Raised when a trusted identity conflicts with persisted user data."""


class TokenVerifier(Protocol):
    def verify(self, token: str) -> dict:
        """Return identity data derived from verified Supabase responses."""


class SupabaseTokenVerifier:
    """Verify a Supabase access token and retrieve its trusted user record."""

    def __init__(
        self,
        supabase_url: str | None,
        publishable_key: str | None,
        http_client_factory: Callable[..., httpx.Client] = httpx.Client,
    ):
        self.supabase_url = (supabase_url or "").rstrip("/")
        self.publishable_key = publishable_key or ""
        self.http_client_factory = http_client_factory
        self.issuer = f"{self.supabase_url}/auth/v1"
        self.jwks_client = PyJWKClient(
            f"{self.issuer}/.well-known/jwks.json",
            timeout=5,
        )

    def _verify_jwt(self, token: str) -> dict:
        try:
            signing_key = self.jwks_client.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=ALLOWED_ALGORITHMS,
                audience="authenticated",
                issuer=self.issuer,
                options={"require": ["exp", "sub", "aud"]},
            )
        except PyJWKClientConnectionError as exc:
            raise AuthProviderUnavailableError(
                "Supabase JWKS is unavailable"
            ) from exc
        except jwt.PyJWTError as exc:
            raise TokenVerificationError("Invalid Supabase access token") from exc
        if claims.get("role") != "authenticated":
            raise TokenVerificationError("Token role is not authenticated")
        return claims

    def verify(self, token: str) -> dict:
        if not self.supabase_url or not self.publishable_key:
            raise AuthProviderUnavailableError(
                "Supabase authentication is not configured"
            )

        try:
            claims = self._verify_jwt(token)
            with self.http_client_factory(timeout=5.0) as client:
                response = client.get(
                    f"{self.issuer}/user",
                    headers={
                        "apikey": self.publishable_key,
                        "Authorization": f"Bearer {token}",
                    },
                )
            if response.status_code in {
                status.HTTP_401_UNAUTHORIZED,
                status.HTTP_403_FORBIDDEN,
            }:
                raise TokenVerificationError("Supabase rejected the access token")
            if response.status_code != status.HTTP_200_OK:
                raise AuthProviderUnavailableError(
                    "Supabase Auth returned an unavailable response"
                )
            user_data = response.json()
        except (TokenVerificationError, AuthProviderUnavailableError):
            raise
        except httpx.RequestError as exc:
            raise AuthProviderUnavailableError(
                "Supabase Auth request failed"
            ) from exc
        except (ValueError, TypeError) as exc:
            raise AuthProviderUnavailableError(
                "Supabase Auth returned malformed JSON"
            ) from exc

        if not isinstance(user_data, dict):
            raise AuthProviderUnavailableError(
                "Supabase Auth returned a malformed user"
            )

        if user_data.get("id") != claims.get("sub"):
            raise TokenVerificationError("Token subject does not match Supabase user")

        metadata = user_data.get("user_metadata", {})
        if not isinstance(metadata, dict):
            raise AuthProviderUnavailableError(
                "Supabase Auth returned malformed user metadata"
            )
        return {
            "sub": claims.get("sub"),
            "email": user_data.get("email"),
            "name": metadata.get("full_name") or metadata.get("name"),
            "role": claims.get("role"),
            "email_confirmed_at": user_data.get("email_confirmed_at"),
        }


@lru_cache(maxsize=1)
def get_token_verifier() -> TokenVerifier:
    """Build the production verifier; tests override this dependency."""
    return SupabaseTokenVerifier(
        settings.SUPABASE_URL,
        settings.SUPABASE_PUBLISHABLE_KEY,
    )


def _synchronize_user(db: Session, identity: dict) -> User:
    subject = identity["sub"]
    email = identity["email"]
    name = identity.get("name") or email
    user = db.get(User, subject)
    if user is None:
        user = User(id=subject, email=email, name=name)
        db.add(user)
    else:
        user.email = email
        user.name = name
    try:
        db.commit()
    except IntegrityError as first_error:
        db.rollback()
        user = db.get(User, subject)
        if user is None:
            raise UserSynchronizationError(
                "Identity conflicts with an existing user"
            ) from first_error
        user.email = email
        user.name = name
        try:
            db.commit()
        except IntegrityError as retry_error:
            db.rollback()
            raise UserSynchronizationError(
                "Identity conflicts with an existing user"
            ) from retry_error
    db.refresh(user)
    return user


def _development_user(db: Session) -> User:
    return _synchronize_user(
        db,
        {
            "sub": "dev_user_001",
            "email": "dev@accesspdf.local",
            "name": "Dev User",
        },
    )


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    verifier: TokenVerifier = Depends(get_token_verifier),
    db: Session = Depends(get_db),
) -> User:
    """Resolve the development identity or authenticate a trial bearer token."""
    if settings.DEPLOYMENT_MODE == "testing":
        return _development_user(db)

    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        identity = verifier.verify(credentials.credentials)
    except AuthProviderUnavailableError:
        logger.warning("Supabase authentication service unavailable")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service unavailable",
        ) from None
    except TokenVerificationError:
        logger.info("Supabase bearer authentication failed")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None

    if (
        not identity.get("sub")
        or not identity.get("email")
        or identity.get("role") != "authenticated"
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authenticated identity",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not identity.get("email_confirmed_at"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="A verified email address is required",
        )

    try:
        return _synchronize_user(db, identity)
    except UserSynchronizationError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Authenticated identity conflicts with an existing account",
        ) from None


def require_user(user: User = Depends(get_current_user)) -> User:
    """Require the authenticated user resolved by the shared dependency."""
    return user


@router.get("/me")
async def get_me(user: User = Depends(require_user)) -> dict:
    """Return the current bearer-authenticated or development identity."""
    return {
        "authenticated": True,
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "created_at": user.created_at.isoformat(),
    }


@router.post("/logout")
async def logout() -> dict:
    """Supabase sessions are cleared by the client that owns them."""
    return {"message": "Sign out with the Supabase client"}
