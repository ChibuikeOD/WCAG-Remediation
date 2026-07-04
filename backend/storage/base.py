"""Provider-neutral artifact storage contracts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


class ArtifactStoreError(Exception):
    """Base class for artifact storage failures."""


class ArtifactNotFound(ArtifactStoreError):
    """Raised when an artifact does not exist."""


class ArtifactAccessDenied(ArtifactStoreError):
    """Raised when an artifact is not owned by the caller or is unsafe to access."""


class InvalidArtifactKey(ArtifactAccessDenied, ValueError):
    """Raised when a key or one of its logical segments is invalid."""


@dataclass(frozen=True)
class ArtifactDownload:
    """A provider-independent download result.

    Local stores return ``local_path``. A remote implementation may instead
    return a short-lived ``signed_url`` without changing the store protocol.
    Exactly one representation must be provided.
    """

    local_path: Path | None = None
    signed_url: str | None = None

    def __post_init__(self) -> None:
        if (self.local_path is None) == (self.signed_url is None):
            raise ValueError("exactly one download representation is required")


class ArtifactStore(ABC):
    """Storage interface for private, user-owned job artifacts."""

    @abstractmethod
    def put(
        self,
        user_id: str,
        job_id: str,
        kind: str,
        source: Path,
        filename: str | None = None,
    ) -> str:
        """Store a file and return its canonical provider-neutral key."""

    @abstractmethod
    def materialize(
        self,
        user_id: str,
        key: str,
        destination: Path,
        *,
        destination_root: Path,
    ) -> Path:
        """Atomically copy an artifact beneath an explicit trusted boundary."""

    @abstractmethod
    def download(self, user_id: str, key: str) -> ArtifactDownload:
        """Return a local path or remote download locator for an owned artifact."""

    @abstractmethod
    def delete(self, user_id: str, key: str) -> None:
        """Delete an owned artifact; absence is idempotently ignored."""

    @abstractmethod
    def delete_job(self, user_id: str, job_id: str) -> None:
        """Delete the exact job subtree; absence is idempotently ignored."""
