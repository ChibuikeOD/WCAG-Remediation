"""Provider-neutral artifact storage contracts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
import re
import unicodedata


class ArtifactStoreError(Exception):
    """Base class for artifact storage failures."""


class ArtifactRetryableError(ArtifactStoreError):
    """Raised when a transient storage failure may succeed on retry."""


class ArtifactConflictError(ArtifactStoreError):
    """Raised when a storage mutation conflicts with current state."""


class ArtifactNotFound(ArtifactStoreError):
    """Raised when an artifact does not exist."""


class ArtifactAccessDenied(ArtifactStoreError):
    """Raised when an artifact is not owned by the caller or is unsafe to access."""


class InvalidArtifactKey(ArtifactAccessDenied, ValueError):
    """Raised when a key or one of its logical segments is invalid."""


_KINDS = frozenset({"original", "remediated", "report"})
_IDENTIFIER = re.compile(r"^[A-Za-z0-9._@+-]+$")


def _validate_segment(value: str, label: str) -> str:
    if not isinstance(value, str) or not value or value in {".", ".."}:
        raise InvalidArtifactKey(f"invalid {label}")
    if "/" in value or "\\" in value:
        raise InvalidArtifactKey(f"{label} must be one path segment")
    if any(unicodedata.category(character) == "Cc" for character in value):
        raise InvalidArtifactKey(f"{label} contains a control character")
    return value


def _validate_identifier(value: str, label: str) -> str:
    _validate_segment(value, label)
    if _IDENTIFIER.fullmatch(value) is None:
        raise InvalidArtifactKey(f"{label} contains unsafe characters")
    return value


@dataclass(frozen=True)
class ArtifactKey:
    """Canonical logical artifact identity with exact UTF-8 semantics."""

    user_id: str
    job_id: str
    kind: str
    filename: str

    def __post_init__(self) -> None:
        _validate_identifier(self.user_id, "user_id")
        _validate_identifier(self.job_id, "job_id")
        _validate_segment(self.kind, "kind")
        if self.kind not in _KINDS:
            raise InvalidArtifactKey(f"unsupported artifact kind: {self.kind}")
        _validate_segment(self.filename, "filename")

    @property
    def key(self) -> str:
        return (
            f"users/{self.user_id}/jobs/{self.job_id}/"
            f"{self.kind}/{self.filename}"
        )

    @classmethod
    def parse(cls, key: str) -> "ArtifactKey":
        if not isinstance(key, str) or key.startswith(("/", "\\")) or "\\" in key:
            raise InvalidArtifactKey("invalid artifact key")
        parts = key.split("/")
        if len(parts) != 6 or parts[0] != "users" or parts[2] != "jobs":
            raise InvalidArtifactKey("artifact key has an invalid shape")
        return cls(parts[1], parts[3], parts[4], parts[5])

    def for_owner(self, user_id: str) -> "ArtifactKey":
        _validate_identifier(user_id, "user_id")
        if self.user_id != user_id:
            raise ArtifactAccessDenied("artifact belongs to another user")
        return self


@dataclass(frozen=True)
class ArtifactDownload:
    """A provider-independent download result.

    Local stores return ``local_path``. A remote implementation may instead
    return a short-lived ``signed_url`` without changing the store protocol.
    Exactly one representation must be provided.
    """

    local_path: Path | None = None
    signed_url: str | None = None
    expires_in_seconds: int | None = None

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

    def close(self) -> None:
        """Release resources owned by the adapter."""

    def __enter__(self) -> "ArtifactStore":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()
