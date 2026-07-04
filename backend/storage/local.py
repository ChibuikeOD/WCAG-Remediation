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
import os
import shutil
import stat
import threading
from pathlib import Path
from uuid import uuid4

from .base import (
    ArtifactAccessDenied,
    ArtifactDownload,
    ArtifactKey,
    ArtifactNotFound,
    ArtifactStore,
    ArtifactStoreError,
)


_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _lstat(path: Path):
    try:
        return os.lstat(path)
    except FileNotFoundError:
        return None


def _is_reparse(path: Path) -> bool:
    details = _lstat(path)
    if details is None:
        return False
    if stat.S_ISLNK(details.st_mode):
        return True
    return os.name == "nt" and bool(
        getattr(details, "st_file_attributes", 0) & _REPARSE_POINT
    )


class LocalArtifactStore(ArtifactStore):
    """Private local storage with collision-safe hashed physical paths."""

    _registry_guard = threading.Lock()
    _root_locks: dict[Path, threading.RLock] = {}

    def __init__(self, root: Path) -> None:
        requested = Path(root).absolute()
        with self._registry_guard:
            self._reject_reparse_ancestors(requested, "artifact store root")
            try:
                requested.mkdir(parents=True, exist_ok=True, mode=0o700)
            except OSError as exc:
                raise ArtifactStoreError("could not create artifact store root") from exc
            self._reject_reparse_ancestors(requested, "artifact store root")
            if not requested.is_dir():
                raise ArtifactStoreError("artifact store root is not a directory")
            self._tighten_directory(requested)
            try:
                resolved = requested.resolve(strict=True)
            except OSError as exc:
                raise ArtifactStoreError("could not resolve artifact store root") from exc
            lock = self._root_locks.setdefault(resolved, threading.RLock())

        self._root_path = requested
        self.root = resolved
        self._lock = lock
        with self._lock:
            self._check_root()
            self._create_safe_directories(self.root / "objects")

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
            self._validate_source(source_path)
            destination = self._path_for_artifact(artifact)
            self._create_safe_directories(destination.parent)
            self._assert_safe_under(self.root, destination)
            self._atomic_write(source_path, destination, boundary=self.root)
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
            destination_path, boundary = self._safe_materialization_destination(
                destination, destination_root
            )
            self._atomic_write(source, destination_path, boundary=boundary)
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
            self._assert_safe_under(self.root, path)
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
            self._assert_safe_under(self.root, job_path)
            if not job_path.exists():
                return
            if not job_path.is_dir():
                raise ArtifactStoreError("job artifact path is not a directory")
            self._assert_tree_safe(job_path)
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
        self._assert_safe_under(self.root, path)
        details = _lstat(path)
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
        self._reject_reparse(self._root_path, "artifact store root")
        try:
            current = self._root_path.resolve(strict=True)
        except OSError as exc:
            raise ArtifactAccessDenied("artifact store root is unavailable") from exc
        if current != self.root or not current.is_dir():
            raise ArtifactAccessDenied("artifact store root changed")
        self._tighten_directory(current)

    def _reject_reparse(self, path: Path, label: str) -> None:
        if _is_reparse(path):
            raise ArtifactAccessDenied(f"{label} contains a reparse point")

    def _reject_reparse_ancestors(self, path: Path, label: str) -> None:
        absolute = Path(path).absolute()
        for component in reversed((absolute, *absolute.parents)):
            self._reject_reparse(component, label)

    def _assert_safe_under(self, boundary: Path, path: Path) -> None:
        boundary = Path(boundary).absolute()
        path = Path(path).absolute()
        try:
            relative = path.relative_to(boundary)
        except ValueError as exc:
            raise ArtifactAccessDenied("path is outside its trusted boundary") from exc
        if ".." in relative.parts:
            raise ArtifactAccessDenied("path is outside its trusted boundary")
        current = boundary
        self._reject_reparse(current, "trusted boundary")
        for part in relative.parts:
            current = current / part
            self._reject_reparse(current, "artifact path")
        try:
            resolved_boundary = boundary.resolve(strict=True)
            resolved_path = path.resolve(strict=False)
        except OSError as exc:
            raise ArtifactAccessDenied("path cannot be resolved safely") from exc
        if not resolved_path.is_relative_to(resolved_boundary):
            raise ArtifactAccessDenied("path is outside its trusted boundary")

    def _assert_tree_safe(self, root: Path) -> None:
        self._assert_safe_under(self.root, root)
        for directory, directories, files in os.walk(root, followlinks=False):
            for name in [*directories, *files]:
                self._reject_reparse(Path(directory) / name, "artifact tree")

    def _create_safe_directories(self, directory: Path) -> None:
        self._assert_safe_under(self.root, directory)
        current = self.root
        for part in directory.relative_to(self.root).parts:
            current = current / part
            self._reject_reparse(current, "artifact directory")
            try:
                current.mkdir(exist_ok=True, mode=0o700)
            except OSError as exc:
                raise ArtifactStoreError("could not create artifact directory") from exc
            self._reject_reparse(current, "artifact directory")
            if not current.is_dir():
                raise ArtifactAccessDenied("artifact directory is unsafe")
            self._tighten_directory(current)

    def _validate_source(self, source: Path) -> None:
        self._reject_reparse(source, "artifact source")
        details = _lstat(source)
        if details is None:
            raise ArtifactNotFound("artifact source does not exist")
        if not stat.S_ISREG(details.st_mode):
            raise ArtifactStoreError("artifact source is not a regular file")

    def _safe_materialization_destination(
        self, destination: Path, destination_root: Path
    ) -> tuple[Path, Path]:
        root_path = Path(destination_root).absolute()
        self._reject_reparse_ancestors(root_path, "materialization root")
        try:
            root_path.mkdir(parents=True, exist_ok=True, mode=0o700)
        except OSError as exc:
            raise ArtifactStoreError("could not create materialization root") from exc
        self._reject_reparse_ancestors(root_path, "materialization root")
        if not root_path.is_dir():
            raise ArtifactAccessDenied("materialization root is unsafe")
        self._tighten_directory(root_path)
        try:
            resolved_root = root_path.resolve(strict=True)
        except OSError as exc:
            raise ArtifactAccessDenied("materialization root cannot be resolved") from exc

        destination_path = Path(destination).absolute()
        self._assert_safe_under(root_path, destination_path)
        relative = destination_path.relative_to(root_path)
        if not relative.parts:
            raise ArtifactAccessDenied("materialization destination is outside its root")
        current = root_path
        for part in relative.parts[:-1]:
            current = current / part
            self._reject_reparse(current, "materialization destination")
            try:
                current.mkdir(exist_ok=True, mode=0o700)
            except OSError as exc:
                raise ArtifactStoreError("could not create destination directory") from exc
            self._reject_reparse(current, "materialization destination")
            if not current.is_dir():
                raise ArtifactAccessDenied(
                    "materialization destination ancestor is not a directory"
                )
            self._tighten_directory(current)
        self._assert_safe_under(resolved_root, destination_path)
        return destination_path, resolved_root

    def _atomic_write(self, source: Path, destination: Path, *, boundary: Path) -> None:
        self._assert_safe_under(boundary, destination)
        temporary = destination.with_name(f".{uuid4().hex}.tmp")
        primary: BaseException | None = None
        cleanup: BaseException | None = None
        try:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            descriptor = os.open(temporary, flags, 0o600)
            os.close(descriptor)
            self._tighten_file(temporary)
            shutil.copyfile(source, temporary)
            self._tighten_file(temporary)
            with temporary.open("r+b") as copied:
                os.fsync(copied.fileno())
            self._assert_safe_under(boundary, destination)
            os.replace(temporary, destination)
            self._assert_safe_under(boundary, destination)
            self._tighten_file(destination)
        except BaseException as exc:
            primary = exc

        try:
            self._cleanup_temp(temporary)
        except BaseException as exc:
            cleanup = exc

        if primary is not None and cleanup is not None:
            raise ArtifactStoreError(
                "atomic artifact write failed; cleanup also failed"
            ) from primary
        if primary is not None:
            if isinstance(primary, ArtifactStoreError):
                raise primary
            raise ArtifactStoreError(f"atomic artifact copy failed: {primary}") from primary
        if cleanup is not None:
            raise ArtifactStoreError("temporary artifact cleanup failed") from cleanup

    def _cleanup_temp(self, temporary: Path) -> None:
        try:
            temporary.unlink(missing_ok=True)
        except OSError as exc:
            raise ArtifactStoreError("temporary artifact cleanup failed") from exc

    def _tighten_directory(self, path: Path) -> None:
        if os.name != "nt":
            try:
                os.chmod(path, 0o700)
            except OSError as exc:
                raise ArtifactStoreError("could not secure artifact directory") from exc

    def _tighten_file(self, path: Path) -> None:
        if os.name != "nt":
            try:
                os.chmod(path, 0o600)
            except OSError as exc:
                raise ArtifactStoreError("could not secure artifact file") from exc
