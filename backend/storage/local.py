"""Secure filesystem implementation of the artifact storage contract.

The configured root must be private to the service account. On POSIX the
adapter enforces owner-only modes. On Windows it rejects reparse points, but
deployment is responsible for applying an account-private ACL. A shared
per-root process lock prevents pathname races between application threads and
adapter instances; protection against another process with write access is a
deployment boundary.
"""

from __future__ import annotations

import hashlib
import shutil
import stat
from pathlib import Path

from . import filesystem
from .base import (
    ArtifactAccessDenied,
    ArtifactDownload,
    ArtifactKey,
    ArtifactNotFound,
    ArtifactStore,
    ArtifactStoreError,
)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class LocalArtifactStore(ArtifactStore):
    """Private local storage with collision-safe hashed physical paths."""

    def __init__(self, root: Path) -> None:
        requested, resolved = filesystem.prepare_private_directory(
            Path(root), "artifact store root"
        )
        lock = filesystem.process_lock_for(resolved)
        self._root_path = requested
        self.root = resolved
        self._lock = lock
        with self._lock:
            self._check_root()
            filesystem.create_safe_directories(self.root, self.root / "objects")

    def put(
        self,
        user_id: str,
        job_id: str,
        kind: str,
        source: Path,
        filename: str | None = None,
    ) -> str:
        source_path = Path(source)
        artifact = ArtifactKey(
            user_id,
            job_id,
            kind,
            source_path.name if filename is None else filename,
        )
        with self._lock:
            self._check_root()
            filesystem.validate_regular_source(source_path)
            destination = self._path_for_artifact(artifact)
            filesystem.create_safe_directories(self.root, destination.parent)
            filesystem.assert_safe_under(self.root, destination)
            filesystem.atomic_write_path(source_path, destination, boundary=self.root)
        return artifact.key

    def materialize(
        self,
        user_id: str,
        key: str,
        destination: Path,
        *,
        destination_root: Path,
    ) -> Path:
        with self._lock:
            self._check_root()
            source = self._owned_artifact(user_id, key)
            destination_path, boundary = filesystem.safe_materialization_destination(
                destination, destination_root
            )
            filesystem.atomic_write_path(source, destination_path, boundary=boundary)
        return Path(destination)

    def download(self, user_id: str, key: str) -> ArtifactDownload:
        with self._lock:
            self._check_root()
            return ArtifactDownload(local_path=self._owned_artifact(user_id, key))

    def delete(self, user_id: str, key: str) -> None:
        artifact = ArtifactKey.parse(key).for_owner(user_id)
        with self._lock:
            self._check_root()
            path = self._path_for_artifact(artifact)
            filesystem.assert_safe_under(self.root, path)
            try:
                path.unlink(missing_ok=True)
            except FileNotFoundError:
                return
            except OSError as exc:
                raise ArtifactStoreError("could not delete artifact") from exc

    def delete_job(self, user_id: str, job_id: str) -> None:
        # ArtifactKey is the single validator for canonical logical segments.
        marker = ArtifactKey(user_id, job_id, "original", "validation")
        with self._lock:
            self._check_root()
            job_path = self._job_path(marker.user_id, marker.job_id)
            filesystem.assert_safe_under(self.root, job_path)
            if not job_path.exists():
                return
            if not job_path.is_dir():
                raise ArtifactStoreError("job artifact path is not a directory")
            filesystem.assert_tree_safe(job_path, self.root)
            try:
                shutil.rmtree(job_path)
            except FileNotFoundError:
                return
            except OSError as exc:
                raise ArtifactStoreError("could not delete job artifacts") from exc

    def _path_for_artifact(self, artifact: ArtifactKey) -> Path:
        return (
            self.root
            / "objects"
            / _digest(f"{artifact.user_id}\0{artifact.job_id}")
            / _digest(artifact.key)
        )

    def _job_path(self, user_id: str, job_id: str) -> Path:
        marker = ArtifactKey(user_id, job_id, "original", "validation")
        return self.root / "objects" / _digest(
            f"{marker.user_id}\0{marker.job_id}"
        )

    def _owned_artifact(self, user_id: str, key: str) -> Path:
        artifact = ArtifactKey.parse(key).for_owner(user_id)
        path = self._path_for_artifact(artifact)
        filesystem.assert_safe_under(self.root, path)
        details = filesystem.lstat(path)
        if details is None:
            raise ArtifactNotFound("artifact does not exist")
        if not stat.S_ISREG(details.st_mode):
            raise ArtifactStoreError("artifact path is not a regular file")
        try:
            resolved = path.resolve(strict=True)
        except OSError as exc:
            raise ArtifactStoreError("could not resolve artifact") from exc
        if not resolved.is_relative_to(self.root):
            raise ArtifactAccessDenied("artifact path escapes the store root")
        return resolved

    def _check_root(self) -> None:
        filesystem.check_private_directory(
            self._root_path, self.root, "artifact store root"
        )
