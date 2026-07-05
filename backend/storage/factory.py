"""Mode-aware construction for artifact storage adapters."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from pydantic import SecretStr

from .base import ArtifactStore, ArtifactStoreError
from .local import LocalArtifactStore
from .supabase import SupabaseArtifactStore

if TYPE_CHECKING:
    from backend.config import Settings


def create_artifact_store(settings: "Settings") -> ArtifactStore:
    """Build the configured adapter without attaching it to app lifecycle."""
    if settings.DEPLOYMENT_MODE == "testing":
        return LocalArtifactStore(settings.ARTIFACT_STORAGE_ROOT)
    if settings.DEPLOYMENT_MODE != "trial":
        raise ArtifactStoreError("unsupported artifact storage mode")
    return SupabaseArtifactStore(
        cast(str, settings.SUPABASE_URL),
        cast(SecretStr, settings.SUPABASE_SECRET_KEY),
        cast(str, settings.SUPABASE_ORIGINALS_BUCKET),
        cast(str, settings.SUPABASE_RESULTS_BUCKET),
        project_ref=cast(str, settings.SUPABASE_PROJECT_REF),
        connect_timeout=settings.SUPABASE_STORAGE_CONNECT_TIMEOUT_SECONDS,
        read_timeout=settings.SUPABASE_STORAGE_READ_TIMEOUT_SECONDS,
        write_timeout=settings.SUPABASE_STORAGE_WRITE_TIMEOUT_SECONDS,
        pool_timeout=settings.SUPABASE_STORAGE_POOL_TIMEOUT_SECONDS,
        signed_url_expires_in_seconds=settings.SUPABASE_STORAGE_SIGNED_URL_SECONDS,
    )
