"""
Authentication Router implementing OpenID Connect (OIDC) via Authlib,
with a fallback Mock SSO mode for development/testing environments.
"""
import logging
from typing import Optional
from fastapi import APIRouter, Depends, Request, HTTPException, status
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.orm import Session
from authlib.integrations.starlette_client import OAuth, OAuthError
from .config import settings
from .database import get_db, User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["Authentication"])

# Initialize OAuth registry
oauth = OAuth()

# Flag indicating if OIDC is configured
OIDC_CONFIGURED = all([
    settings.OIDC_CLIENT_ID,
    settings.OIDC_CLIENT_SECRET,
    settings.OIDC_DISCOVERY_URL,
    settings.OIDC_CLIENT_ID != "your_oidc_client_id"
])

if OIDC_CONFIGURED:
    try:
        oauth.register(
            name="oidc",
            client_id=settings.OIDC_CLIENT_ID,
            client_secret=settings.OIDC_CLIENT_SECRET,
            server_metadata_url=settings.OIDC_DISCOVERY_URL,
            client_kwargs={"scope": "openid profile email"}
        )
        logger.info("OIDC SSO Auth client registered successfully.")
    except Exception as e:
        logger.error(f"Failed to register OIDC client: {e}. Falling back to Mock SSO.")
        OIDC_CONFIGURED = False
else:
    logger.info("OIDC SSO credentials not fully configured. Running in Mock SSO mode.")


def get_current_user(request: Request, db: Session = Depends(get_db)) -> Optional[User]:
    """
    Dependency provider to retrieve the logged-in user from the session.
    Returns None if no user is authenticated.
    """
    # ── Auth-bypass mode (testing/demo only) ──────────────────────
    if settings.DISABLE_AUTH:
        mock_id = "dev_user_001"
        mock_email = "dev@accesspdf.local"
        mock_name = "Dev User"
        
        user = db.query(User).filter(User.id == mock_id).first()
        if not user:
            try:
                user = User(id=mock_id, email=mock_email, name=mock_name)
                db.add(user)
                db.commit()
                db.refresh(user)
            except Exception as e:
                db.rollback()
                logger.error(f"Failed to create mock user in db: {e}")
                return User(id=mock_id, email=mock_email, name=mock_name)
        return user

    user_id = request.session.get("user_id")
    if not user_id:
        return None
    return db.query(User).filter(User.id == user_id).first()


def require_user(user: Optional[User] = Depends(get_current_user)) -> User:
    """
    Dependency provider that enforces authentication.
    Raises 401 Unauthorized if the user is not authenticated.
    """
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please log in through SSO."
        )
    return user


@router.get("/login")
async def login(request: Request, redirect_to: Optional[str] = "/"):
    """
    Initiates the authentication flow.
    - DISABLE_AUTH=true : instantly creates a mock session, no click required.
    - OIDC configured   : redirects to the identity provider.
    - Neither           : mock SSO fallback for local development.
    """
    request.session["auth_redirect_to"] = redirect_to

    # ── Auth-bypass mode (testing only) ──────────────────────────
    if settings.DISABLE_AUTH:
        logger.info("DISABLE_AUTH=true: auto-logging in as mock user.")
        request.session["user_id"]    = "dev_user_001"
        request.session["user_name"]  = "Dev User"
        request.session["user_email"] = "dev@accesspdf.local"
        frontend_url = settings.CORS_ORIGINS[1] if len(settings.CORS_ORIGINS) > 1 else settings.CORS_ORIGINS[0]
        return RedirectResponse(url=f"{frontend_url}{redirect_to}")

    if OIDC_CONFIGURED:
        callback_uri = str(request.url_for("auth_callback"))
        # Force HTTPS redirect URI in production/non-localhost
        if "localhost" not in callback_uri and callback_uri.startswith("http:"):
            callback_uri = callback_uri.replace("http:", "https:")
        return await oauth.oidc.authorize_redirect(request, callback_uri)

    # Mock authentication flow (OIDC not configured)
    logger.info("Mock Login: Authenticating developer user.")
    mock_id    = "mock_umass_prof_101"
    mock_email = "prof_johndoe@umass.edu"
    mock_name  = "Professor John Doe"

    db = next(get_db())
    try:
        user = db.query(User).filter(User.id == mock_id).first()
        if not user:
            user = User(id=mock_id, email=mock_email, name=mock_name)
            db.add(user)
            db.commit()
            db.refresh(user)

        request.session["user_id"]    = user.id
        request.session["user_name"]  = user.name
        request.session["user_email"] = user.email
    finally:
        db.close()

    frontend_url = settings.CORS_ORIGINS[1] if len(settings.CORS_ORIGINS) > 1 else settings.CORS_ORIGINS[0]
    return RedirectResponse(url=f"{frontend_url}{redirect_to}")


@router.get("/callback")
async def auth_callback(request: Request, db: Session = Depends(get_db)):
    """
    OIDC identity provider redirect callback endpoint.
    Exchanges authorization code for tokens and registers user.
    """
    if not OIDC_CONFIGURED:
        raise HTTPException(status_code=400, detail="OIDC is not configured. Use /login for Mock SSO.")
        
    try:
        token = await oauth.oidc.authorize_access_token(request)
        userinfo = token.get("userinfo")
        if not userinfo:
            # Fallback parsing ID token if userinfo endpoint is not present
            userinfo = await oauth.oidc.parse_id_token(request, token)
            
        sub = userinfo.get("sub")
        email = userinfo.get("email")
        name = userinfo.get("name", email)
        
        if not sub or not email:
            raise HTTPException(status_code=400, detail="Invalid token claims: email and sub are required.")
            
        # Synchronize user with database
        user = db.query(User).filter(User.id == sub).first()
        if not user:
            user = User(id=sub, email=email, name=name)
            db.add(user)
        else:
            user.name = name  # Update name in case it changed on IdP
        db.commit()
        db.refresh(user)
        
        # Set session variables
        request.session["user_id"] = user.id
        request.session["user_name"] = user.name
        request.session["user_email"] = user.email
        
        redirect_to = request.session.pop("auth_redirect_to", "/")
        frontend_url = settings.CORS_ORIGINS[1] if len(settings.CORS_ORIGINS) > 1 else settings.CORS_ORIGINS[0]
        return RedirectResponse(url=f"{frontend_url}{redirect_to}")
        
    except OAuthError as oe:
        logger.error(f"OAuth callback validation error: {oe.description}")
        raise HTTPException(status_code=400, detail=f"Authentication failed: {oe.description}")
    except Exception as e:
        logger.error(f"OAuth callback unexpected error: {e}")
        raise HTTPException(status_code=500, detail="Internal SSO communication error.")


@router.get("/logout")
async def logout(request: Request):
    """
    Clears the login session and redirects user to login.
    """
    request.session.clear()
    frontend_url = settings.CORS_ORIGINS[1] if len(settings.CORS_ORIGINS) > 1 else settings.CORS_ORIGINS[0]
    return RedirectResponse(url=frontend_url)


@router.get("/me")
async def get_me(request: Request, user: Optional[User] = Depends(get_current_user)):
    """
    Returns user details for active sessions.
    When DISABLE_AUTH=true, always returns a mock authenticated user so the
    frontend skips the login screen without any click required.
    """
    # ── Auth-bypass mode (testing only) ──────────────────────────
    if settings.DISABLE_AUTH:
        return {
            "authenticated": True,
            "id":    "dev_user_001",
            "name":  "Dev User",
            "email": "dev@accesspdf.local",
        }

    if not user:
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"authenticated": False, "message": "No active session"}
        )
    return {
        "authenticated": True,
        "id":         user.id,
        "name":       user.name,
        "email":      user.email,
        "created_at": user.created_at.isoformat(),
    }
