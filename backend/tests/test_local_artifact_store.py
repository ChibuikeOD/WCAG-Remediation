from __future__ import annotations

import os
from pathlib import Path

import pytest

from backend.storage import (
    ArtifactAccessDenied,
    ArtifactNotFound,
    ArtifactStoreError,
    InvalidArtifactKey,
    LocalArtifactStore,
)


def _source(tmp_path: Path, content: bytes = b"first") -> Path:
    source = tmp_path / "source.pdf"
    source.write_bytes(content)
    return source


def _symlink_or_skip(link: Path, target: Path, *, directory: bool = False) -> None:
    try:
        link.symlink_to(target, target_is_directory=directory)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"real symlinks are unavailable: {exc}")


def test_round_trip_put_download_materialize_and_delete(tmp_path: Path) -> None:
    store = LocalArtifactStore(tmp_path / "private")
    source = _source(tmp_path, b"artifact")

    key = store.put("user-1", "job-1", "original", source)

    assert key == "users/user-1/jobs/job-1/original/source.pdf"
    download = store.download("user-1", key)
    assert download.local_path is not None
    assert download.signed_url is None
    assert download.local_path.read_bytes() == b"artifact"

    destination_root = tmp_path / "materialized"
    destination = destination_root / "copy.pdf"
    assert (
        store.materialize(
            "user-1", key, destination, destination_root=destination_root
        )
        == destination
    )
    assert destination.read_bytes() == b"artifact"

    store.delete("user-1", key)
    store.delete("user-1", key)
    with pytest.raises(ArtifactNotFound):
        store.download("user-1", key)


def test_put_uses_requested_basename_and_atomically_overwrites(tmp_path: Path) -> None:
    store = LocalArtifactStore(tmp_path / "private")
    source = _source(tmp_path, b"old")
    key = store.put("user", "job", "remediated", source, "result.pdf")
    source.write_bytes(b"new")

    assert store.put("user", "job", "remediated", source, "result.pdf") == key
    assert store.download("user", key).local_path.read_bytes() == b"new"  # type: ignore[union-attr]
    assert not list((tmp_path / "private").rglob("*.tmp"))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("user_id", ""),
        ("user_id", "."),
        ("user_id", ".."),
        ("user_id", "a/b"),
        ("user_id", "a\\b"),
        ("user_id", "C:\\absolute"),
        ("user_id", "unsafe id"),
        ("user_id", "stream:name"),
        ("user_id", "bad\x00id"),
        ("job_id", ""),
        ("job_id", "../job"),
        ("job_id", "a\\b"),
        ("job_id", "job*name"),
        ("job_id", "bad\x1fid"),
        ("kind", "unknown"),
        ("kind", "../original"),
        ("filename", ""),
        ("filename", "."),
        ("filename", ".."),
        ("filename", "dir/file.pdf"),
        ("filename", "dir\\file.pdf"),
        ("filename", "/absolute.pdf"),
        ("filename", "stream:name.pdf"),
        ("filename", "bad\x7fname.pdf"),
    ],
)
def test_put_rejects_invalid_key_segments(tmp_path: Path, field: str, value: str) -> None:
    store = LocalArtifactStore(tmp_path / "private")
    values = {
        "user_id": "user",
        "job_id": "job",
        "kind": "report",
        "filename": "report.json",
    }
    values[field] = value

    with pytest.raises(InvalidArtifactKey):
        store.put(source=_source(tmp_path), **values)


@pytest.mark.parametrize(
    "key",
    [
        "",
        "/users/user/jobs/job/original/a.pdf",
        "users/user/jobs/job/original/../a.pdf",
        "users/user/jobs/job/original/a\\b.pdf",
        "users/user/jobs/job/not-allowed/a.pdf",
        "users/user/jobs/job/original/a.pdf/extra",
        "users//jobs/job/original/a.pdf",
        "C:\\users\\user\\jobs\\job\\original\\a.pdf",
    ],
)
def test_read_rejects_malformed_or_traversing_keys(tmp_path: Path, key: str) -> None:
    store = LocalArtifactStore(tmp_path / "private")

    with pytest.raises(InvalidArtifactKey):
        store.download("user", key)


def test_put_rejects_missing_directory_and_symlink_sources(tmp_path: Path) -> None:
    store = LocalArtifactStore(tmp_path / "private")
    with pytest.raises(ArtifactNotFound):
        store.put("user", "job", "original", tmp_path / "missing.pdf")
    with pytest.raises(ArtifactStoreError):
        store.put("user", "job", "original", tmp_path)

    target = _source(tmp_path)
    link = tmp_path / "source-link.pdf"
    _symlink_or_skip(link, target)
    with pytest.raises(ArtifactStoreError):
        store.put("user", "job", "original", link)


def test_cross_user_access_is_denied_and_names_are_isolated(tmp_path: Path) -> None:
    store = LocalArtifactStore(tmp_path / "private")
    source = _source(tmp_path, b"one")
    first = store.put("user-one", "job", "original", source, "same.pdf")
    source.write_bytes(b"two")
    second = store.put("user-two", "job", "original", source, "same.pdf")
    source.write_bytes(b"three")
    third = store.put("user-one", "other-job", "original", source, "same.pdf")

    assert len({first, second, third}) == 3
    assert store.download("user-one", first).local_path.read_bytes() == b"one"  # type: ignore[union-attr]
    assert store.download("user-two", second).local_path.read_bytes() == b"two"  # type: ignore[union-attr]
    assert store.download("user-one", third).local_path.read_bytes() == b"three"  # type: ignore[union-attr]
    for operation in (store.download, store.delete):
        with pytest.raises(ArtifactAccessDenied):
            operation("user-two", first)


def test_existing_artifact_symlink_is_never_followed(tmp_path: Path) -> None:
    store = LocalArtifactStore(tmp_path / "private")
    source = _source(tmp_path)
    key = "users/user/jobs/job/original/source.pdf"
    artifact = tmp_path / "private" / key
    artifact.parent.mkdir(parents=True)
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"outside")
    _symlink_or_skip(artifact, outside)

    with pytest.raises(ArtifactAccessDenied):
        store.put("user", "job", "original", source)
    with pytest.raises(ArtifactAccessDenied):
        store.download("user", key)
    with pytest.raises(ArtifactAccessDenied):
        store.delete("user", key)
    assert outside.read_bytes() == b"outside"


def test_root_symlink_is_rejected(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    link = tmp_path / "store-link"
    _symlink_or_skip(link, outside, directory=True)

    with pytest.raises(ArtifactAccessDenied):
        LocalArtifactStore(link)


def test_mocked_key_resolution_escape_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = LocalArtifactStore(tmp_path / "private")
    key = store.put("user", "job", "original", _source(tmp_path))
    artifact = store.root.joinpath(*key.split("/"))
    outside = tmp_path / "outside.pdf"
    original_resolve = Path.resolve

    def redirected_resolve(path: Path, strict: bool = False) -> Path:
        if path == artifact:
            return outside
        return original_resolve(path, strict=strict)

    monkeypatch.setattr(Path, "resolve", redirected_resolve)
    with pytest.raises(ArtifactAccessDenied, match="escapes"):
        store.download("user", key)


def test_mocked_root_replacement_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = LocalArtifactStore(tmp_path / "private")
    original_resolve = Path.resolve
    outside = tmp_path / "replacement"

    def redirected_resolve(path: Path, strict: bool = False) -> Path:
        if path == store._root_path:  # deterministic replacement simulation
            return outside
        return original_resolve(path, strict=strict)

    monkeypatch.setattr(Path, "resolve", redirected_resolve)
    with pytest.raises(ArtifactAccessDenied, match="root changed"):
        store.delete_job("user", "job")


def test_materialize_does_not_overwrite_destination_symlink(tmp_path: Path) -> None:
    store = LocalArtifactStore(tmp_path / "private")
    key = store.put("user", "job", "report", _source(tmp_path), "report.json")
    outside = tmp_path / "outside.json"
    outside.write_bytes(b"outside")
    destination = tmp_path / "destination.json"
    _symlink_or_skip(destination, outside)

    with pytest.raises(ArtifactAccessDenied):
        store.materialize("user", key, destination, destination_root=tmp_path)
    assert outside.read_bytes() == b"outside"


def test_materialize_rejects_symlinked_destination_ancestor(tmp_path: Path) -> None:
    store = LocalArtifactStore(tmp_path / "private")
    key = store.put("user", "job", "original", _source(tmp_path))
    destination_root = tmp_path / "exports"
    destination_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    linked_directory = destination_root / "linked"
    _symlink_or_skip(linked_directory, outside, directory=True)

    with pytest.raises(ArtifactAccessDenied):
        store.materialize(
            "user",
            key,
            linked_directory / "copy.pdf",
            destination_root=destination_root,
        )
    assert not (outside / "copy.pdf").exists()


def test_materialize_rejects_symlinked_destination_root(tmp_path: Path) -> None:
    store = LocalArtifactStore(tmp_path / "private")
    key = store.put("user", "job", "original", _source(tmp_path))
    outside = tmp_path / "outside"
    outside.mkdir()
    destination_root = tmp_path / "exports-link"
    _symlink_or_skip(destination_root, outside, directory=True)

    with pytest.raises(ArtifactAccessDenied):
        store.materialize(
            "user",
            key,
            destination_root / "copy.pdf",
            destination_root=destination_root,
        )
    assert not (outside / "copy.pdf").exists()


def test_materialize_rejects_destination_outside_root(tmp_path: Path) -> None:
    store = LocalArtifactStore(tmp_path / "private")
    key = store.put("user", "job", "original", _source(tmp_path))
    destination_root = tmp_path / "exports"

    with pytest.raises(ArtifactAccessDenied, match="outside"):
        store.materialize(
            "user",
            key,
            destination_root / ".." / "escaped.pdf",
            destination_root=destination_root,
        )
    assert not (tmp_path / "escaped.pdf").exists()


def test_materialize_rejects_mocked_destination_resolution_escape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = LocalArtifactStore(tmp_path / "private")
    key = store.put("user", "job", "original", _source(tmp_path))
    destination_root = tmp_path / "exports"
    destination = destination_root / "copy.pdf"
    outside = tmp_path / "outside.pdf"
    original_resolve = Path.resolve

    def redirected_resolve(path: Path, strict: bool = False) -> Path:
        if path == destination:
            return outside
        return original_resolve(path, strict=strict)

    monkeypatch.setattr(Path, "resolve", redirected_resolve)
    with pytest.raises(ArtifactAccessDenied, match="outside"):
        store.materialize(
            "user", key, destination, destination_root=destination_root
        )


def test_put_cleans_temp_file_when_replace_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = LocalArtifactStore(tmp_path / "private")

    def fail_replace(source: Path, destination: Path) -> None:
        raise OSError("injected replace failure")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(ArtifactStoreError, match="replace failure"):
        store.put("user", "job", "original", _source(tmp_path))
    assert not list((tmp_path / "private").rglob("*.tmp"))


def test_materialize_cleans_temp_file_when_copy_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = LocalArtifactStore(tmp_path / "private")
    key = store.put("user", "job", "original", _source(tmp_path))
    destination = tmp_path / "exports" / "copy.pdf"

    def fail_copy(source: Path, target: Path) -> None:
        raise OSError("injected copy failure")

    monkeypatch.setattr("backend.storage.local.shutil.copyfile", fail_copy)
    with pytest.raises(ArtifactStoreError, match="copy failure"):
        store.materialize(
            "user", key, destination, destination_root=destination.parent
        )
    assert not list(destination.parent.glob("*.tmp"))


def test_delete_job_is_exact_and_idempotent(tmp_path: Path) -> None:
    store = LocalArtifactStore(tmp_path / "private")
    source = _source(tmp_path)
    deleted = store.put("user", "job", "original", source, "a.pdf")
    retained_job = store.put("user", "job-other", "original", source, "a.pdf")
    retained_user = store.put("user-other", "job", "original", source, "a.pdf")

    store.delete_job("user", "job")
    store.delete_job("user", "job")

    with pytest.raises(ArtifactNotFound):
        store.download("user", deleted)
    assert store.download("user", retained_job).local_path is not None
    assert store.download("user-other", retained_user).local_path is not None
    with pytest.raises(InvalidArtifactKey):
        store.delete_job("user", "../job-other")


def test_delete_job_rejects_symlinked_job_subtree(tmp_path: Path) -> None:
    store = LocalArtifactStore(tmp_path / "private")
    outside = tmp_path / "outside"
    outside.mkdir()
    marker = outside / "keep.txt"
    marker.write_text("keep")
    job = tmp_path / "private" / "users" / "user" / "jobs" / "job"
    job.parent.mkdir(parents=True)
    _symlink_or_skip(job, outside, directory=True)

    with pytest.raises(ArtifactAccessDenied):
        store.delete_job("user", "job")
    assert marker.read_text() == "keep"
