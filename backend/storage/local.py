"""Secure filesystem implementation of the artifact storage contract."""

from __future__ import annotations

import os
import re
import shutil
import stat
import unicodedata
from pathlib import Path
from uuid import uuid4

from .base import (
    ArtifactAccessDenied,
    ArtifactDownload,
    ArtifactNotFound,
    ArtifactStore,
    ArtifactStoreError,
    InvalidArtifactKey,
)


_KINDS = frozenset({"original", "remediated", "report"})
_IDENTIFIER = re.compile(r"^[A-Za-z0-9._@+-]+$")
_WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


def _validate_segment(value: str, label: str) -> str:
    if not isinstance(value, str) or not value or value in {".", ".."}:
        raise InvalidArtifactKey(f"invalid {label}")
    if "/" in value or "\\" in value:
        raise InvalidArtifactKey(f"{label} must be one path segment")
    if any(unicodedata.category(character) == "Cc" for character in value):
        raise InvalidArtifactKey(f"{label} contains a control character")
    return value


def _validate_kind(kind: str) -> str:
    _validate_segment(kind, "kind")
    if kind not in _KINDS:
        raise InvalidArtifactKey(f"unsupported artifact kind: {kind}")
    return kind


def _validate_identifier(value: str, label: str) -> str:
    _validate_segment(value, label)
    if _IDENTIFIER.fullmatch(value) is None:
        raise InvalidArtifactKey(f"{label} contains unsafe characters")
    return value


def _validate_filename(filename: str) -> str:
    _validate_segment(filename, "filename")
    if any(character in '<>:"|?*' for character in filename):
        raise InvalidArtifactKey("filename contains unsafe characters")
    if filename.endswith((" ", ".")):
        raise InvalidArtifactKey("filename has an unsafe suffix")
    if filename.split(".", 1)[0].upper() in _WINDOWS_RESERVED:
        raise InvalidArtifactKey("filename is reserved by the local filesystem")
    return filename


class LocalArtifactStore(ArtifactStore):
    """Private artifact storage rooted in one local directory.

    The store owns validation of logical keys and their source paths. Callers
    choose an explicit trusted ``destination_root`` for ``materialize``; the
    destination must remain beneath that root and no component at or below the
    root may be a symlink.
    """

    def __init__(self, root: Path) -> None:
        requested = Path(root).absolute()
        if requested.is_symlink():
            raise ArtifactAccessDenied("artifact store root cannot be a symlink")
        try:
            requested.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ArtifactStoreError(f"could not create artifact store root: {exc}") from exc
        if requested.is_symlink():
            raise ArtifactAccessDenied("artifact store root cannot be a symlink")
        try:
            resolved = requested.resolve(strict=True)
        except OSError as exc:
            raise ArtifactStoreError(f"could not resolve artifact store root: {exc}") from exc
        if not resolved.is_dir():
            raise ArtifactStoreError("artifact store root is not a directory")
        self._root_path = requested
        self.root = resolved

    def put(
        self,
        user_id: str,
        job_id: str,
        kind: str,
        source: Path,
        filename: str | None = None,
    ) -> str:
        user_id = _validate_identifier(user_id, "user_id")
        job_id = _validate_identifier(job_id, "job_id")
        kind = _validate_kind(kind)
        source_path = Path(source)
        selected_name = source_path.name if filename is None else filename
        selected_name = _validate_filename(selected_name)
        self._validate_source(source_path)

        key = f"users/{user_id}/jobs/{job_id}/{kind}/{selected_name}"
        destination = self._path_for_key(key)
        self._create_safe_directories(destination.parent)
        self._assert_no_symlinks(destination)
        self._atomic_copy(source_path, destination)
        return key

    def materialize(
        self,
        user_id: str,
        key: str,
        destination: Path,
        *,
        destination_root: Path,
    ) -> Path:
        source = self._owned_artifact(user_id, key)
        destination_path = self._safe_materialization_destination(
            destination, destination_root
        )
        self._atomic_copy(source, destination_path)
        return Path(destination)

    def download(self, user_id: str, key: str) -> ArtifactDownload:
        return ArtifactDownload(local_path=self._owned_artifact(user_id, key))

    def delete(self, user_id: str, key: str) -> None:
        owner, _, _, _ = self._parse_key(key)
        _validate_identifier(user_id, "user_id")
        if owner != user_id:
            raise ArtifactAccessDenied("artifact belongs to another user")
        path = self._path_for_key(key)
        self._assert_no_symlinks(path)
        if not path.exists():
            return
        if not path.is_file():
            raise ArtifactStoreError("artifact path is not a regular file")
        try:
            path.unlink()
        except OSError as exc:
            raise ArtifactStoreError(f"could not delete artifact: {exc}") from exc

    def delete_job(self, user_id: str, job_id: str) -> None:
        user_id = _validate_identifier(user_id, "user_id")
        job_id = _validate_identifier(job_id, "job_id")
        self._check_root()
        job_path = self.root / "users" / user_id / "jobs" / job_id
        self._ensure_contained(job_path)
        self._assert_no_symlinks(job_path)
        if not job_path.exists():
            return
        if not job_path.is_dir():
            raise ArtifactStoreError("job artifact path is not a directory")
        for directory, directories, files in os.walk(job_path, followlinks=False):
            for name in [*directories, *files]:
                if (Path(directory) / name).is_symlink():
                    raise ArtifactAccessDenied("job artifact subtree contains a symlink")
        try:
            shutil.rmtree(job_path)
        except OSError as exc:
            raise ArtifactStoreError(f"could not delete job artifacts: {exc}") from exc

    def _check_root(self) -> None:
        if self._root_path.is_symlink():
            raise ArtifactAccessDenied("artifact store root cannot be a symlink")
        try:
            current = self._root_path.resolve(strict=True)
        except OSError as exc:
            raise ArtifactAccessDenied(f"artifact store root is unavailable: {exc}") from exc
        if current != self.root or not current.is_dir():
            raise ArtifactAccessDenied("artifact store root changed")

    def _parse_key(self, key: str) -> tuple[str, str, str, str]:
        if not isinstance(key, str) or key.startswith(("/", "\\")) or "\\" in key:
            raise InvalidArtifactKey("invalid artifact key")
        parts = key.split("/")
        if len(parts) != 6 or parts[0] != "users" or parts[2] != "jobs":
            raise InvalidArtifactKey("artifact key has an invalid shape")
        user_id = _validate_identifier(parts[1], "user_id")
        job_id = _validate_identifier(parts[3], "job_id")
        kind = _validate_kind(parts[4])
        filename = _validate_filename(parts[5])
        return user_id, job_id, kind, filename

    def _path_for_key(self, key: str) -> Path:
        self._parse_key(key)
        self._check_root()
        path = self.root.joinpath(*key.split("/"))
        self._ensure_contained(path)
        return path

    def _ensure_contained(self, path: Path) -> None:
        try:
            resolved = path.resolve(strict=False)
        except OSError as exc:
            raise ArtifactAccessDenied(f"artifact path cannot be resolved: {exc}") from exc
        if not resolved.is_relative_to(self.root):
            raise ArtifactAccessDenied("artifact path escapes the store root")

    def _assert_no_symlinks(self, path: Path) -> None:
        self._ensure_contained(path)
        relative = path.relative_to(self.root)
        current = self.root
        for part in relative.parts:
            current = current / part
            try:
                mode = current.lstat().st_mode
            except FileNotFoundError:
                continue
            except OSError as exc:
                raise ArtifactStoreError(f"could not inspect artifact path: {exc}") from exc
            if stat.S_ISLNK(mode):
                raise ArtifactAccessDenied("artifact path contains a symlink")

    def _create_safe_directories(self, directory: Path) -> None:
        self._ensure_contained(directory)
        current = self.root
        for part in directory.relative_to(self.root).parts:
            current = current / part
            if current.is_symlink():
                raise ArtifactAccessDenied("artifact directory contains a symlink")
            try:
                current.mkdir(exist_ok=True)
            except OSError as exc:
                raise ArtifactStoreError(f"could not create artifact directory: {exc}") from exc
            if current.is_symlink() or not current.is_dir():
                raise ArtifactAccessDenied("artifact directory is unsafe")

    def _validate_source(self, source: Path) -> None:
        if source.is_symlink():
            raise ArtifactStoreError("artifact source cannot be a symlink")
        if not source.exists():
            raise ArtifactNotFound(f"artifact source does not exist: {source}")
        if not source.is_file():
            raise ArtifactStoreError("artifact source is not a regular file")

    def _safe_materialization_destination(
        self, destination: Path, destination_root: Path
    ) -> Path:
        root_path = Path(destination_root).absolute()
        if root_path.is_symlink():
            raise ArtifactAccessDenied("materialization root cannot be a symlink")
        try:
            root_path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ArtifactStoreError(
                f"could not create materialization root: {exc}"
            ) from exc
        if root_path.is_symlink() or not root_path.is_dir():
            raise ArtifactAccessDenied("materialization root is unsafe")
        try:
            resolved_root = root_path.resolve(strict=True)
        except OSError as exc:
            raise ArtifactAccessDenied(
                f"materialization root cannot be resolved: {exc}"
            ) from exc

        destination_path = Path(destination).absolute()
        try:
            relative = destination_path.relative_to(root_path)
        except ValueError as exc:
            raise ArtifactAccessDenied(
                "materialization destination is outside its root"
            ) from exc
        if not relative.parts or ".." in relative.parts:
            raise ArtifactAccessDenied(
                "materialization destination is outside its root"
            )

        try:
            resolved_destination = destination_path.resolve(strict=False)
        except OSError as exc:
            raise ArtifactAccessDenied(
                f"materialization destination cannot be resolved: {exc}"
            ) from exc
        if not resolved_destination.is_relative_to(resolved_root):
            raise ArtifactAccessDenied(
                "materialization destination is outside its root"
            )

        current = root_path
        for index, part in enumerate(relative.parts):
            current = current / part
            if current.is_symlink():
                raise ArtifactAccessDenied(
                    "materialization destination contains a symlink"
                )
            is_leaf = index == len(relative.parts) - 1
            if current.exists() and not is_leaf and not current.is_dir():
                raise ArtifactAccessDenied(
                    "materialization destination ancestor is not a directory"
                )
            if not is_leaf:
                try:
                    current.mkdir(exist_ok=True)
                except OSError as exc:
                    raise ArtifactStoreError(
                        f"could not create destination directory: {exc}"
                    ) from exc
                if current.is_symlink() or not current.is_dir():
                    raise ArtifactAccessDenied(
                        "materialization destination ancestor is unsafe"
                    )

        return destination_path

    def _owned_artifact(self, user_id: str, key: str) -> Path:
        owner, _, _, _ = self._parse_key(key)
        _validate_identifier(user_id, "user_id")
        if owner != user_id:
            raise ArtifactAccessDenied("artifact belongs to another user")
        path = self._path_for_key(key)
        self._assert_no_symlinks(path)
        if not path.exists():
            raise ArtifactNotFound(f"artifact does not exist: {key}")
        if not path.is_file():
            raise ArtifactStoreError("artifact path is not a regular file")
        try:
            resolved = path.resolve(strict=True)
        except OSError as exc:
            raise ArtifactStoreError(f"could not resolve artifact: {exc}") from exc
        if not resolved.is_relative_to(self.root):
            raise ArtifactAccessDenied("artifact path escapes the store root")
        return resolved

    def _atomic_copy(self, source: Path, destination: Path) -> None:
        if destination.is_symlink():
            raise ArtifactAccessDenied("destination cannot be a symlink")
        temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
        try:
            shutil.copyfile(source, temporary)
            # Windows requires a writable descriptor for fsync.
            with temporary.open("r+b") as copied:
                os.fsync(copied.fileno())
            if destination.is_symlink():
                raise ArtifactAccessDenied("destination cannot be a symlink")
            os.replace(temporary, destination)
        except ArtifactStoreError:
            raise
        except OSError as exc:
            raise ArtifactStoreError(f"atomic artifact copy failed: {exc}") from exc
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
