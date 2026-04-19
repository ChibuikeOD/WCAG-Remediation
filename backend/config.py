"""
Configuration settings for the WCAG Accessibility Remediation Platform.
"""
import os
from pathlib import Path
from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # Application
    APP_NAME: str = "WCAG Accessibility Remediation Platform"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True
    
    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    
    # File paths
    BASE_DIR: Path = Path(__file__).parent.parent
    RULES_DIR: Path = BASE_DIR / "rules"
    UPLOAD_DIR: Path = BASE_DIR / "uploads"
    OUTPUT_DIR: Path = BASE_DIR / "output"
    OPENDATALOADER_ROOT: Path = BASE_DIR / "opendataloader-pdf-main"
    
    # Processing limits
    MAX_FILE_SIZE_MB: int = 50
    MAX_PAGES_PDF: int = 100
    
    # Playwright settings
    PLAYWRIGHT_HEADLESS: bool = True
    PLAYWRIGHT_TIMEOUT: int = 30000  # milliseconds
    
    # CORS
    CORS_ORIGINS: list = ["http://localhost:3000", "http://localhost:5173"]
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()

# In serverless demo deployments it's common to serve the frontend and API
# from the same origin, but preview domains vary. Allow opting into permissive
# CORS via env without changing code.
_allow_all = str(getattr(settings, "CORS_ALLOW_ALL", os.getenv("CORS_ALLOW_ALL", "false"))).lower() in {
    "1",
    "true",
    "yes",
    "on",
}
if _allow_all:
    settings.CORS_ORIGINS = ["*"]

# Vercel (and many serverless platforms) mount the code package read-only.
# Use /tmp for runtime writeable directories.
_is_serverless = any(
    os.getenv(k) for k in ("VERCEL", "AWS_LAMBDA_FUNCTION_NAME", "FUNCTIONS_WORKER_RUNTIME")
)
if _is_serverless:
    settings.UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "/tmp/uploads"))
    settings.OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "/tmp/output"))

# Ensure runtime directories exist (must be writeable).
settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
settings.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)





