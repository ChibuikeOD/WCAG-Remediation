"""Storage-aware retention for uploaded documents and remediation artifacts."""

import asyncio
import logging
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from .config import settings
from .database import RemediationJob, SessionLocal, UploadedFile
from .storage import ArtifactAccessDenied, ArtifactKey, ArtifactStore

logger = logging.getLogger(__name__)


def _delete_original(store: ArtifactStore, file_rec: UploadedFile) -> None:
    """Delete a logical artifact, or a contained testing-only legacy upload."""
    try:
        ArtifactKey.parse(file_rec.file_path).for_owner(file_rec.owner_id)
    except (ArtifactAccessDenied, ValueError, TypeError):
        if settings.DEPLOYMENT_MODE != "testing":
            raise ArtifactAccessDenied("legacy retention paths are disabled") from None
        legacy = Path(file_rec.file_path)
        if not legacy.is_absolute():
            raise ArtifactAccessDenied("legacy retention path must be absolute")
        root = settings.UPLOAD_DIR.resolve(strict=True)
        resolved = legacy.resolve(strict=False)
        if not resolved.is_relative_to(root):
            raise ArtifactAccessDenied("legacy retention path escapes upload root")
        if resolved.exists() and not resolved.is_file():
            raise ArtifactAccessDenied("legacy retention path is not a file")
        resolved.unlink(missing_ok=True)
        return
    store.delete(file_rec.owner_id, file_rec.file_path)


async def clean_expired_documents(
    *,
    store: ArtifactStore,
    session_factory=SessionLocal,
    run_once: bool = False,
    sleep_seconds: float = 3600,
):
    """Delete expired storage objects before removing their file metadata.

    Each record uses an independent transaction. Any storage failure leaves its
    metadata intact so a later cycle can retry without blocking other records.
    """
    logger.info("Starting Data Retention Runner...")
    while True:
        cutoff = datetime.utcnow() - timedelta(hours=settings.RETENTION_PERIOD_HOURS)
        discovery = session_factory()
        try:
            expired_ids = list(discovery.scalars(
                select(UploadedFile.id).where(UploadedFile.uploaded_at < cutoff)
            ))
        finally:
            discovery.close()

        for file_id in expired_ids:
            db = session_factory()
            try:
                file_rec = db.get(UploadedFile, file_id)
                if file_rec is None:
                    continue
                job_ids = list(db.scalars(
                    select(RemediationJob.id).where(RemediationJob.file_id == file_id)
                ))
                _delete_original(store, file_rec)
                for job_id in job_ids:
                    store.delete_job(file_rec.owner_id, job_id)
                db.delete(file_rec)
                db.commit()
            except Exception:
                db.rollback()
                logger.exception("Retention cleanup failed for file %s", file_id)
            finally:
                db.close()

        if run_once:
            return
        await asyncio.sleep(sleep_seconds)
