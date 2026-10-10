"""Deployment checks for the native PDF runtime; no external HTTP calls."""
import shutil
from pathlib import Path

from sqlalchemy import text

from .config import settings
from .database import engine


def deployment_readiness() -> dict[str, bool]:
    from .opendataloader_layout import OpenDataLoaderLayoutAnalyzer
    from .pdf_remediator_fixes import _resolve_tessdata
    import sys

    root = Path(__file__).resolve().parent.parent
    candidates = [root / "pdfua_remediator_cpp" / "build" / "pdfua-remediator-cli",
                  root / "pdfua_remediator_cpp" / "build" / "Release" / "pdfua-remediator-cli"]
    if sys.platform == "win32":
        candidates = [root / "pdfua_remediator_cpp" / "build" / "Release" / "pdfua-remediator-cli.exe"]
    checks = {"database": False,
              "tagging": settings.DISABLE_OPENDATALOADER or (
                  OpenDataLoaderLayoutAnalyzer.is_available() and any(p.is_file() for p in candidates)),
              "ocr": settings.DISABLE_OCR or _resolve_tessdata() is not None,
              "qpdf": shutil.which("qpdf") is not None}
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        checks["database"] = True
    except Exception:
        pass
    return checks
