import asyncio
from pathlib import Path
import threading

import pytest
from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.config import Settings
from backend.storage import ArtifactAccessDenied, ArtifactDownload, ArtifactKey
from backend.storage.factory import create_artifact_store
from backend import database


class RecordingStore:
    def __init__(self, source: Path):
        self.source = source
        self.materializations = []

    def materialize(self, user_id, key, destination, *, destination_root):
        ArtifactKey.parse(key).for_owner(user_id)
        destination.write_bytes(self.source.read_bytes())
        self.materializations.append((user_id, key, destination, destination_root))
        return destination


class ThreadRecordingStore:
    def __init__(self, source: Path):
        self.source = source
        self.materialize_thread = None
        self.download_thread = None

    def materialize(self, user_id, key, destination, *, destination_root):
        self.materialize_thread = threading.get_ident()
        ArtifactKey.parse(key).for_owner(user_id)
        destination.write_bytes(self.source.read_bytes())
        return destination

    def download(self, user_id, key):
        self.download_thread = threading.get_ident()
        ArtifactKey.parse(key).for_owner(user_id)
        return ArtifactDownload(signed_url="https://example.test/download")


def test_factory_testing_local_root_override_is_deployment_scoped(tmp_path):
    configured = tmp_path / "configured"
    dedicated = tmp_path / "dedicated"
    config = Settings(
        DEPLOYMENT_MODE="testing",
        ARTIFACT_STORAGE_ROOT=configured,
        _env_file=None,
    )

    store = create_artifact_store(config, local_root=dedicated)

    assert store.root == dedicated.resolve()
    assert not configured.exists()


def test_materialized_upload_is_unique_and_cleaned(tmp_path, monkeypatch):
    from backend import main

    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-private")
    store = RecordingStore(source)
    key = ArtifactKey("owner", "file-id", "original", "source.pdf").key

    with main.materialized_upload(store, "owner", key, "source.pdf") as first:
        first_root = first.parent
        assert first.read_bytes() == b"%PDF-private"
        with main.materialized_upload(store, "owner", key, "source.pdf") as second:
            assert second.parent != first.parent
            assert second.read_bytes() == b"%PDF-private"
        assert not second.exists()

    assert not first_root.exists()
    assert not first.exists()


def test_async_artifact_helpers_offload_blocking_store_calls(tmp_path):
    from backend import main

    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-private")
    key = ArtifactKey("owner", "file-id", "original", "source.pdf").key
    store = ThreadRecordingStore(source)

    async def exercise():
        event_loop_thread = threading.get_ident()
        async with main.materialized_upload_async(
            store, "owner", key, "source.pdf"
        ) as materialized:
            assert materialized.read_bytes() == b"%PDF-private"
        response = await main.artifact_download_response_async(
            store,
            "owner",
            key,
            filename="source.pdf",
            media_type="application/pdf",
        )
        return event_loop_thread, response

    event_loop_thread, response = asyncio.run(exercise())

    assert response.status_code == 303
    assert store.materialize_thread is not None
    assert store.download_thread is not None
    assert store.materialize_thread != event_loop_thread
    assert store.download_thread != event_loop_thread


def test_trial_rejects_legacy_absolute_upload_path(tmp_path, monkeypatch):
    from backend import main

    legacy = tmp_path / "upload.pdf"
    legacy.write_bytes(b"%PDF-private")
    monkeypatch.setattr(main.settings, "DEPLOYMENT_MODE", "trial")

    with pytest.raises(ArtifactAccessDenied):
        with main.materialized_upload(object(), "owner", str(legacy), "upload.pdf"):
            pass


def test_testing_legacy_upload_must_be_contained(tmp_path, monkeypatch):
    from backend import main

    upload_root = tmp_path / "uploads"
    upload_root.mkdir()
    allowed = upload_root / "allowed.pdf"
    allowed.write_bytes(b"allowed")
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"outside")
    monkeypatch.setattr(main.settings, "DEPLOYMENT_MODE", "testing")
    monkeypatch.setattr(main.settings, "UPLOAD_DIR", upload_root)

    with main.materialized_upload(object(), "owner", str(allowed), "allowed.pdf") as path:
        assert path == allowed.resolve()
    with pytest.raises(ArtifactAccessDenied):
        with main.materialized_upload(object(), "owner", str(outside), "outside.pdf"):
            pass


def test_lifespan_owns_one_mode_aware_store_and_closes_it(monkeypatch, tmp_path):
    from backend import main

    class OwnedStore:
        def __init__(self):
            self.closed = 0

        def close(self):
            self.closed += 1

    store = OwnedStore()
    factory_calls = []
    retention_started = asyncio.Event()

    def factory(config, *, local_root):
        factory_calls.append((config, local_root))
        return store

    async def retention(*, store, session_factory):
        assert store is main.app.state.artifact_store
        retention_started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(main, "create_artifact_store", factory)
    monkeypatch.setattr(main, "clean_expired_documents", retention)
    monkeypatch.setattr(main, "init_db", lambda: None)
    monkeypatch.setattr(main.settings, "ARTIFACT_STORAGE_ROOT", tmp_path / "private")

    async def exercise():
        async with main.lifespan(main.app):
            await asyncio.wait_for(retention_started.wait(), timeout=1)
            assert main.app.state.artifact_store is store
            assert factory_calls == [(main.settings, tmp_path / "private")]

    asyncio.run(exercise())

    assert store.closed == 1


class RetentionStore:
    def __init__(self, fail_key=None):
        self.fail_key = fail_key
        self.deleted = []
        self.deleted_jobs = []

    def delete(self, user_id, key):
        if key == self.fail_key:
            raise RuntimeError("storage unavailable")
        self.deleted.append((user_id, key))

    def delete_job(self, user_id, job_id):
        self.deleted_jobs.append((user_id, job_id))


def _retention_database(tmp_path, original_key):
    engine = create_engine(f"sqlite:///{tmp_path / 'retention.db'}")
    database.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        session.add(database.User(id="owner", email="owner@example.com", name="Owner"))
        session.add(database.UploadedFile(
            id="expired-file", filename="source.pdf", file_type="pdf",
            file_path=original_key, file_size=1,
            uploaded_at=datetime.utcnow() - timedelta(hours=13), owner_id="owner",
        ))
        session.add(database.RemediationJob(
            id="job-1", user_id="owner", file_id="expired-file", status="succeeded",
            page_count=1, idempotency_key="job-1",
        ))
        session.commit()
    return engine, factory


def test_retention_deletes_store_artifacts_before_file_metadata(tmp_path):
    from backend.retention_runner import clean_expired_documents

    key = ArtifactKey("owner", "expired-file", "original", "source.pdf").key
    engine, factory = _retention_database(tmp_path, key)
    store = RetentionStore()

    asyncio.run(clean_expired_documents(
        store=store, session_factory=factory, run_once=True
    ))

    with factory() as session:
        assert session.get(database.UploadedFile, "expired-file") is None
        assert session.get(database.RemediationJob, "job-1") is not None
    assert store.deleted == [("owner", key)]
    assert store.deleted_jobs == [("owner", "job-1")]
    engine.dispose()


def test_retention_storage_failure_keeps_metadata_for_retry(tmp_path):
    from backend.retention_runner import clean_expired_documents

    key = ArtifactKey("owner", "expired-file", "original", "source.pdf").key
    engine, factory = _retention_database(tmp_path, key)
    store = RetentionStore(fail_key=key)

    asyncio.run(clean_expired_documents(
        store=store, session_factory=factory, run_once=True
    ))

    with factory() as session:
        assert session.get(database.UploadedFile, "expired-file") is not None
    assert store.deleted_jobs == []
    engine.dispose()
