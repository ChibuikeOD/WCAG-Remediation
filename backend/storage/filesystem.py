"""Shared private filesystem safety helpers for artifact stores."""

from __future__ import annotations

import os
import shutil
import stat
import threading
from collections.abc import Iterable
from pathlib import Path
from uuid import uuid4

from .base import ArtifactAccessDenied, ArtifactNotFound, ArtifactStoreError


_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)

_registry_guard = threading.Lock()
_root_locks: dict[Path, threading.RLock] = {}


def process_lock_for(root: Path) -> threading.RLock:
    with _registry_guard:
        return _root_locks.setdefault(Path(root), threading.RLock())


def lstat(path: Path):
    try:
        return os.lstat(path)
    except FileNotFoundError:
        return None


def is_reparse(path: Path) -> bool:
    details = lstat(path)
    if details is None:
        return False
    if stat.S_ISLNK(details.st_mode):
        return True
    return os.name == "nt" and bool(
        getattr(details, "st_file_attributes", 0) & _REPARSE_POINT
    )


def reject_reparse(path: Path, label: str) -> None:
    if is_reparse(path):
        raise ArtifactAccessDenied(f"{label} contains a reparse point")


def reject_reparse_ancestors(path: Path, label: str) -> None:
    absolute = Path(path).absolute()
    for component in reversed((absolute, *absolute.parents)):
        reject_reparse(component, label)


def tighten_directory(path: Path) -> None:
    if os.name != "nt":
        try:
            os.chmod(path, 0o700)
        except OSError as exc:
            raise ArtifactStoreError("could not secure artifact directory") from exc


def tighten_file(path: Path) -> None:
    if os.name != "nt":
        try:
            os.chmod(path, 0o600)
        except OSError as exc:
            raise ArtifactStoreError("could not secure artifact file") from exc


def prepare_private_directory(path: Path, label: str) -> tuple[Path, Path]:
    requested = Path(path).absolute()
    reject_reparse_ancestors(requested, label)
    try:
        requested.mkdir(parents=True, exist_ok=True, mode=0o700)
    except OSError as exc:
        raise ArtifactStoreError(f"could not create {label}") from exc
    reject_reparse_ancestors(requested, label)
    if not requested.is_dir():
        raise ArtifactStoreError(f"{label} is not a directory")
    tighten_directory(requested)
    try:
        resolved = requested.resolve(strict=True)
    except OSError as exc:
        raise ArtifactStoreError(f"could not resolve {label}") from exc
    return requested, resolved


def check_private_directory(requested: Path, resolved: Path, label: str) -> None:
    reject_reparse(requested, label)
    try:
        current = requested.resolve(strict=True)
    except OSError as exc:
        raise ArtifactAccessDenied(f"{label} is unavailable") from exc
    if current != resolved or not current.is_dir():
        raise ArtifactAccessDenied(f"{label} changed")
    tighten_directory(current)


def assert_safe_under(boundary: Path, path: Path) -> None:
    boundary = Path(boundary).absolute()
    path = Path(path).absolute()
    try:
        relative = path.relative_to(boundary)
    except ValueError as exc:
        raise ArtifactAccessDenied("path is outside its trusted boundary") from exc
    if ".." in relative.parts:
        raise ArtifactAccessDenied("path is outside its trusted boundary")
    current = boundary
    reject_reparse(current, "trusted boundary")
    for part in relative.parts:
        current = current / part
        reject_reparse(current, "artifact path")
    try:
        resolved_boundary = boundary.resolve(strict=True)
        resolved_path = path.resolve(strict=False)
    except OSError as exc:
        raise ArtifactAccessDenied("path cannot be resolved safely") from exc
    if not resolved_path.is_relative_to(resolved_boundary):
        raise ArtifactAccessDenied("path is outside its trusted boundary")


def assert_tree_safe(root: Path, boundary: Path) -> None:
    assert_safe_under(boundary, root)
    for directory, directories, files in os.walk(root, followlinks=False):
        for name in [*directories, *files]:
            reject_reparse(Path(directory) / name, "artifact tree")


def create_safe_directories(boundary: Path, directory: Path) -> None:
    boundary = Path(boundary)
    directory = Path(directory)
    assert_safe_under(boundary, directory)
    current = boundary
    for part in directory.relative_to(boundary).parts:
        current = current / part
        reject_reparse(current, "artifact directory")
        try:
            current.mkdir(exist_ok=True, mode=0o700)
        except OSError as exc:
            raise ArtifactStoreError("could not create artifact directory") from exc
        reject_reparse(current, "artifact directory")
        if not current.is_dir():
            raise ArtifactAccessDenied("artifact directory is unsafe")
        tighten_directory(current)


def validate_regular_source(source: Path) -> None:
    reject_reparse(source, "artifact source")
    details = lstat(source)
    if details is None:
        raise ArtifactNotFound("artifact source does not exist")
    if not stat.S_ISREG(details.st_mode):
        raise ArtifactStoreError("artifact source is not a regular file")


def safe_materialization_destination(
    destination: Path, destination_root: Path
) -> tuple[Path, Path]:
    root_path = Path(destination_root).absolute()
    reject_reparse_ancestors(root_path, "materialization root")
    try:
        root_path.mkdir(parents=True, exist_ok=True, mode=0o700)
    except OSError as exc:
        raise ArtifactStoreError("could not create materialization root") from exc
    reject_reparse_ancestors(root_path, "materialization root")
    if not root_path.is_dir():
        raise ArtifactAccessDenied("materialization root is unsafe")
    tighten_directory(root_path)
    try:
        resolved_root = root_path.resolve(strict=True)
    except OSError as exc:
        raise ArtifactAccessDenied("materialization root cannot be resolved") from exc

    destination_path = Path(destination).absolute()
    assert_safe_under(root_path, destination_path)
    relative = destination_path.relative_to(root_path)
    if not relative.parts:
        raise ArtifactAccessDenied("materialization destination is outside its root")
    current = root_path
    for part in relative.parts[:-1]:
        current = current / part
        reject_reparse(current, "materialization destination")
        try:
            current.mkdir(exist_ok=True, mode=0o700)
        except OSError as exc:
            raise ArtifactStoreError("could not create destination directory") from exc
        reject_reparse(current, "materialization destination")
        if not current.is_dir():
            raise ArtifactAccessDenied(
                "materialization destination ancestor is not a directory"
            )
        tighten_directory(current)
    assert_safe_under(resolved_root, destination_path)
    return destination_path, resolved_root


def atomic_write_path(source: Path, destination: Path, *, boundary: Path) -> None:
    def copy_to(target: Path) -> None:
        shutil.copyfile(source, target)
        with target.open("ab") as output:
            output.flush()
            os.fsync(output.fileno())

    atomic_write_with_writer(copy_to, destination, boundary=boundary)


def atomic_write_chunks(
    chunks: Iterable[bytes], destination: Path, *, boundary: Path
) -> None:
    def write_chunks(target: Path) -> None:
        with target.open("wb") as output:
            for chunk in chunks:
                if chunk:
                    output.write(chunk)
            output.flush()
            os.fsync(output.fileno())

    atomic_write_with_writer(write_chunks, destination, boundary=boundary)


def atomic_write_with_writer(
    writer, destination: Path, *, boundary: Path
) -> None:
    assert_safe_under(boundary, destination)
    temporary = destination.with_name(f".{uuid4().hex}.tmp")
    primary: BaseException | None = None
    cleanup: BaseException | None = None
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        descriptor = os.open(temporary, flags, 0o600)
        os.close(descriptor)
        tighten_file(temporary)
        writer(temporary)
        tighten_file(temporary)
        assert_safe_under(boundary, destination)
        os.replace(temporary, destination)
        assert_safe_under(boundary, destination)
        tighten_file(destination)
    except BaseException as exc:
        primary = exc

    try:
        cleanup_temp(temporary)
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


def cleanup_temp(temporary: Path) -> None:
    try:
        temporary.unlink(missing_ok=True)
    except OSError as exc:
        raise ArtifactStoreError("temporary artifact cleanup failed") from exc
