"""
Configuration settings for the WCAG Accessibility Remediation Platform.
"""
import glob
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

# Proactively add standard Windows Tesseract path to PATH to prevent OCR failure if terminal environment is stale
_tesseract_win_path = r"C:\Program Files\Tesseract-OCR"
if os.name == "nt" and os.path.exists(_tesseract_win_path):
    if _tesseract_win_path not in os.environ.get("PATH", ""):
        os.environ["PATH"] = _tesseract_win_path + os.pathsep + os.environ.get("PATH", "")


def _normalize_tessdata_prefix() -> None:
    """Ensure TESSDATA_PREFIX points at the 'tessdata' folder itself.

    PyMuPDF/MuPDF reads TESSDATA_PREFIX at ``import fitz`` time and expects the
    folder that actually contains ``*.traineddata`` (not its parent, which is
    the classic Tesseract-CLI convention). We normalize/auto-detect it here,
    before fitz is imported anywhere, so OCR works across hosts and conventions.
    """
    def _has_traineddata(d: str) -> bool:
        try:
            return bool(d) and os.path.isdir(d) and bool(glob.glob(os.path.join(d, "*.traineddata")))
        except Exception:
            return False

    env = os.environ.get("TESSDATA_PREFIX")
    if env:
        env = env.rstrip("/\\")
        if _has_traineddata(env):
            os.environ["TESSDATA_PREFIX"] = env
            return
        nested = os.path.join(env, "tessdata")
        if _has_traineddata(nested):
            os.environ["TESSDATA_PREFIX"] = nested
            return

    candidates = [
        "/usr/share/tesseract-ocr/4.00/tessdata",
        "/usr/share/tesseract-ocr/5/tessdata",
        "/usr/share/tesseract-ocr/tessdata",
        "/usr/share/tessdata",
        "/usr/local/share/tessdata",
        r"C:\Program Files\Tesseract-OCR\tessdata",
        r"C:\Program Files (x86)\Tesseract-OCR\tessdata",
    ]
    candidates.extend(sorted(glob.glob("/usr/share/tesseract-ocr/*/tessdata"), reverse=True))
    for c in candidates:
        if _has_traineddata(c):
            os.environ["TESSDATA_PREFIX"] = c
            return


_normalize_tessdata_prefix()

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Literal, Optional


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=(".env", "backend/.env"),
        env_file_encoding="utf-8",
        hide_input_in_errors=True,
    )
    
    # Application
    APP_NAME: str = "WCAG Accessibility Remediation Platform"
    APP_VERSION: str = "1.0.0"
    DEPLOYMENT_MODE: Literal["trial", "testing"] = "testing"
    DEBUG: bool = True
    SECRET_KEY: str = "development_secret_key_change_me_to_something_secure"
    
    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    
    # File paths
    BASE_DIR: Path = Path(__file__).parent.parent
    RULES_DIR: Path = BASE_DIR / "rules"
    UPLOAD_DIR: Path = BASE_DIR / "uploads"
    OUTPUT_DIR: Path = BASE_DIR / "output"
    ARTIFACT_STORAGE_ROOT: Path = BASE_DIR / ".artifacts"
    OPENDATALOADER_ROOT: Path = BASE_DIR / "opendataloader-pdf-main"
    LAYOUTLM_MODEL_DIR: Path = BASE_DIR / "layoutLM_trained"
    
    # Database
    DATABASE_URL: str = "sqlite:///./wcag_platform.db"
    
    # Data Retention (in hours, clamped between 2 and 24 to support session resumption)
    RETENTION_PERIOD_HOURS: int = Field(default=12, ge=2, le=24)
    
    # OpenID Connect (OIDC) Authentication
    OIDC_CLIENT_ID: Optional[str] = None
    OIDC_CLIENT_SECRET: Optional[str] = None
    OIDC_DISCOVERY_URL: Optional[str] = None

    # Supabase identity and private trial artifact storage
    SUPABASE_URL: Optional[str] = None
    SUPABASE_PUBLISHABLE_KEY: Optional[str] = None
    SUPABASE_SECRET_KEY: Optional[SecretStr] = None
    SUPABASE_PROJECT_REF: Optional[str] = None
    SUPABASE_ORIGINALS_BUCKET: Optional[str] = None
    SUPABASE_RESULTS_BUCKET: Optional[str] = None
    SUPABASE_STORAGE_CONNECT_TIMEOUT_SECONDS: float = Field(default=5.0, gt=0.0)
    SUPABASE_STORAGE_READ_TIMEOUT_SECONDS: float = Field(default=30.0, gt=0.0)
    SUPABASE_STORAGE_WRITE_TIMEOUT_SECONDS: float = Field(default=30.0, gt=0.0)
    SUPABASE_STORAGE_POOL_TIMEOUT_SECONDS: float = Field(default=5.0, gt=0.0)
    SUPABASE_STORAGE_SIGNED_URL_SECONDS: int = Field(default=300, gt=0)

    # Development / Testing
    # Set DISABLE_AUTH=true to skip the login screen entirely.
    # /auth/me will return a pre-authenticated mock user automatically.
    # Never enable this in production.
    DISABLE_AUTH: bool = True
    
    # Disable PyTorch/LayoutLMv3 (large model, high RAM) by default
    DISABLE_LAYOUTLM: bool = True

    # Disable system OCR (Tesseract) by default (now enabled since we have Starter plan)
    DISABLE_OCR: bool = False

    # Enable OpenDataLoader (Java) structure tagging by default
    # Requires Java and the compiled C++ remediator binary to be present
    DISABLE_OPENDATALOADER: bool = False
    
    # Processing limits
    MAX_FILE_SIZE_MB: int = 50
    MAX_PAGES_PDF: int = 100
    PDF_UPLOAD_VALIDATION_TIMEOUT_SECONDS: float = Field(default=10.0, gt=0.0)

    # Hard wall-clock cap (seconds) for external PDF tooling subprocesses
    # (OpenDataLoader/Java layout extraction and the C++ tagging engine).
    # Without this, a wedged or thrashing subprocess hangs the request forever.
    PDF_SUBPROCESS_TIMEOUT_SECONDS: int = 180
    
    # Playwright settings
    PLAYWRIGHT_HEADLESS: bool = True
    PLAYWRIGHT_TIMEOUT: int = 30000  # milliseconds
    
    # AI Alt-text generation
    DEEPSEEK_API_KEY: Optional[str] = None

    # Ambiguous PDF Unicode verification
    GEMINI_API_KEY: Optional[str] = None
    GEMINI_MODEL: str = "gemini-3.1-flash-lite"
    GEMINI_API_ENDPOINT: str = (
        "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    )
    PDF_UNICODE_LLM_ENABLED: bool = True
    PDF_UNICODE_LLM_MAX_ATTEMPTS: int = Field(default=3, ge=1, le=5)
    PDF_UNICODE_LLM_MIN_CONFIDENCE: float = Field(default=0.98, ge=0.0, le=1.0)
    PDF_UNICODE_LLM_TIMEOUT_SECONDS: float = Field(default=45.0, gt=0.0)
    PDF_UNICODE_LLM_MAX_OCCURRENCES: int = Field(default=3, ge=1, le=5)
    
    # CORS
    CORS_ORIGINS: list = [
        "http://localhost:3000",
        "http://localhost:5173",
        "https://wcag-remediation.vercel.app"
    ]
    CORS_ALLOW_ALL: bool = False

    @model_validator(mode="after")
    def validate_trial_deployment(self) -> "Settings":
        if self.DEPLOYMENT_MODE != "trial":
            return self

        if self.DISABLE_AUTH:
            raise ValueError("DISABLE_AUTH must be false in trial mode")
        if self.CORS_ALLOW_ALL:
            raise ValueError("CORS_ALLOW_ALL must be false in trial mode")

        required_supabase_settings = (
            "SUPABASE_URL",
            "SUPABASE_PUBLISHABLE_KEY",
            "SUPABASE_SECRET_KEY",
            "SUPABASE_PROJECT_REF",
            "SUPABASE_ORIGINALS_BUCKET",
            "SUPABASE_RESULTS_BUCKET",
        )
        missing_settings = []
        for name in required_supabase_settings:
            value = getattr(self, name)
            if isinstance(value, SecretStr):
                value = value.get_secret_value()
            if not (value or "").strip():
                missing_settings.append(name)
        if missing_settings:
            raise ValueError(
                "Trial mode requires Supabase settings: "
                + ", ".join(missing_settings)
            )
        if self.SUPABASE_ORIGINALS_BUCKET == self.SUPABASE_RESULTS_BUCKET:
            raise ValueError("Trial mode requires distinct Supabase artifact buckets")

        project_ref = self.SUPABASE_PROJECT_REF or ""
        if re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", project_ref) is None:
            raise ValueError("Trial mode requires a valid SUPABASE_PROJECT_REF")
        try:
            parsed = urlsplit(self.SUPABASE_URL or "")
            port = parsed.port
        except ValueError as exc:
            raise ValueError("Trial mode requires a valid SUPABASE_URL") from exc
        expected_hostname = f"{project_ref}.supabase.co"
        if (
            parsed.scheme != "https"
            or parsed.hostname != expected_hostname
            or parsed.username is not None
            or parsed.password is not None
            or port is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
            or parsed.netloc != expected_hostname
        ):
            raise ValueError("Trial mode requires a valid SUPABASE_URL")

        bucket_pattern = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
        for label, bucket in (
            ("originals bucket", self.SUPABASE_ORIGINALS_BUCKET),
            ("results bucket", self.SUPABASE_RESULTS_BUCKET),
        ):
            if (
                bucket is None
                or bucket in {".", ".."}
                or bucket_pattern.fullmatch(bucket) is None
            ):
                raise ValueError(f"Trial mode requires a safe Supabase {label}")

        return self


settings = Settings()


def _enforce_runtime_cors_isolation(configured_settings: Settings) -> None:
    """Fail closed after env-derived CORS overrides are applied."""
    if configured_settings.DEPLOYMENT_MODE != "trial":
        return
    if configured_settings.CORS_ORIGINS != ["https://pdfaccess.org"]:
        raise ValueError(
            "CORS_ORIGINS_LIST must be exactly https://pdfaccess.org in trial mode"
        )

# Allow configuring allowed origins via a comma-separated env variable
_origins_env = os.getenv("CORS_ORIGINS_LIST")
if _origins_env:
    settings.CORS_ORIGINS = [o.strip() for o in _origins_env.split(",") if o.strip()]

# In serverless demo deployments it's common to serve the frontend and API
# from the same origin, but preview domains vary. Allow opting into permissive
# CORS via env without changing code.
_allow_all = str(settings.CORS_ALLOW_ALL).lower() in {
    "1",
    "true",
    "yes",
    "on",
}
if _allow_all:
    settings.CORS_ORIGINS = ["*"]

_enforce_runtime_cors_isolation(settings)

# Vercel (and many serverless platforms) mount the code package read-only.
# Use /tmp for runtime writeable directories.
#
# Note: Vercel's env surface differs between runtimes, so we use multiple
# signals + a read-only `/var/task` fallback.
_vercel_signals = (
    "VERCEL",
    "VERCEL_ENV",
    "VERCEL_REGION",
    "VERCEL_URL",
    "NOW_REGION",
)
_is_serverless = any(os.getenv(k) for k in _vercel_signals) or any(
    os.getenv(k) for k in ("AWS_LAMBDA_FUNCTION_NAME", "AWS_EXECUTION_ENV", "FUNCTIONS_WORKER_RUNTIME")
)

try:
    if Path("/var/task").exists() and not os.access("/var/task", os.W_OK):
        _is_serverless = True
except Exception:
    # If the platform doesn't support this check, ignore it.
    pass
if _is_serverless:
    settings.UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "/tmp/uploads"))
    settings.OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "/tmp/output"))

# Ensure runtime directories exist (must be writeable).
settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
settings.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)





