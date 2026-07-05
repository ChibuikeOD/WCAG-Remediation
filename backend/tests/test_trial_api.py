"""API contract tests for trial balances, uploads, and metered remediation."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess
import threading
import time

import fitz
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

import backend.database as database
import backend.main as main_module
import backend.pdf_accessibility as pdf_accessibility_module
from backend.auth import get_token_verifier, require_user
from backend.config import settings
from backend.main import app
from backend.models import AccessibilityReport, DocumentInfo
from backend.storage import ArtifactKey, LocalArtifactStore


def pdf_bytes(page_count=1):
    document = fitz.open()
    for _ in range(page_count):
        document.new_page()
    content = document.tobytes()
    document.close()
    return content


class CountingUpload:
    def __init__(self, filename, chunks):
        self.filename = filename
        self.chunks = list(chunks)
        self.read_calls = 0

    async def read(self, size=-1):
        self.read_calls += 1
        return self.chunks.pop(0) if self.chunks else b""


@pytest.fixture()
def trial_client(tmp_path, monkeypatch):
    test_engine = create_engine(
        f"sqlite:///{tmp_path / 'trial-api.db'}",
        connect_args={"check_same_thread": False},
    )
    session_factory = sessionmaker(bind=test_engine, expire_on_commit=False)
    upload_dir = tmp_path / "uploads"
    output_dir = tmp_path / "output"
    upload_dir.mkdir()
    output_dir.mkdir()

    monkeypatch.setattr(database, "engine", test_engine)
    monkeypatch.setattr(database, "SessionLocal", session_factory)
    monkeypatch.setattr(main_module, "SessionLocal", session_factory)
    monkeypatch.setattr(settings, "UPLOAD_DIR", upload_dir)
    monkeypatch.setattr(settings, "OUTPUT_DIR", output_dir)
    monkeypatch.setattr(settings, "DEPLOYMENT_MODE", "trial")
    monkeypatch.setattr(
        main_module,
        "create_artifact_store",
        lambda _settings, **_kwargs: LocalArtifactStore(tmp_path / "artifacts"),
    )

    async def idle_retention_worker(**_kwargs):
        await asyncio.Event().wait()

    monkeypatch.setattr(main_module, "clean_expired_documents", idle_retention_worker)
    database.Base.metadata.create_all(test_engine)
    with session_factory() as session:
        user = database.User(
            id="verified-user", email="person@gmail.com", name="Verified User"
        )
        session.add(user)
        session.commit()

    def verified_user():
        with session_factory() as session:
            return session.get(database.User, "verified-user")

    app.dependency_overrides[require_user] = verified_user
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client, session_factory, tmp_path
    finally:
        app.dependency_overrides.clear()
        test_engine.dispose()


def upload_pdf(client, pages=2, filename="source.pdf"):
    return client.post(
        "/upload",
        files={"file": (filename, pdf_bytes(pages), "application/pdf")},
    )


def seed_report(session_factory, file_id, report_id="report-1"):
    report = AccessibilityReport(
        id=report_id,
        document=DocumentInfo(filename="source.pdf", file_type="pdf"),
    )
    with session_factory() as session:
        session.add(
            database.AccessibilityReport(
                id=report_id, file_id=file_id, report_json=report.model_dump_json()
            )
        )
        session.commit()
    return report_id


def install_fast_pdf_analyzer(monkeypatch):
    class FastPDFAnalyzer:
        def __init__(self, file_path):
            self.file_path = file_path

        def analyze(self):
            with fitz.open(self.file_path) as document:
                page_count = document.page_count
            return {
                "metadata": {"page_count": page_count},
                "issues": [],
            }

        def close(self):
            pass

    monkeypatch.setattr(
        pdf_accessibility_module, "PDFAccessibilityAnalyzer", FastPDFAnalyzer
    )


def test_trial_me_returns_balance_and_does_not_duplicate_grant(trial_client):
    client, session_factory, _ = trial_client

    first = client.get("/trial/me")
    second = client.get("/trial/me")

    assert first.status_code == second.status_code == 200
    assert first.json() == {
        "granted_pages": 200,
        "consumed_pages": 0,
        "reserved_pages": 0,
        "remaining_pages": 200,
        "normalized_domain": "gmail.com",
        "eligibility_rule_version": "2026-07-04",
    }
    with session_factory() as session:
        grants = session.scalars(select(database.TrialLedgerEntry)).all()
        assert len(grants) == 1


def test_trial_me_is_not_available_in_testing_mode(trial_client, monkeypatch):
    client, session_factory, _ = trial_client
    monkeypatch.setattr(settings, "DEPLOYMENT_MODE", "testing")

    response = client.get("/trial/me")

    assert response.status_code == 404
    with session_factory() as session:
        assert session.query(database.TrialAccount).count() == 0


def test_testing_mode_trial_me_returns_404_before_authentication(
    trial_client, monkeypatch
):
    client, session_factory, _ = trial_client
    app.dependency_overrides.clear()
    monkeypatch.setattr(settings, "DEPLOYMENT_MODE", "testing")

    class ForbiddenVerifier:
        def __init__(self):
            self.called = False

        def verify(self, token):
            self.called = True
            raise AssertionError("verifier must not run")

    verifier = ForbiddenVerifier()
    provider_calls = []

    def forbidden_provider():
        provider_calls.append(True)
        return verifier

    app.dependency_overrides[get_token_verifier] = forbidden_provider

    response = client.get("/trial/me")

    assert response.status_code == 404
    assert provider_calls == []
    assert verifier.called is False
    with session_factory() as session:
        assert session.get(database.User, "dev_user_001") is None


def test_trial_me_without_auth_is_blocked_by_existing_auth(trial_client):
    client, _, _ = trial_client
    app.dependency_overrides.clear()

    response = client.get("/trial/me")

    assert response.status_code == 401


def test_trial_me_with_unverified_email_is_blocked_by_existing_auth(trial_client):
    client, _, _ = trial_client
    app.dependency_overrides.clear()

    class UnverifiedTokenVerifier:
        def verify(self, token):
            return {
                "sub": "unverified-user",
                "email": "unverified@gmail.com",
                "name": "Unverified",
                "role": "authenticated",
                "email_confirmed_at": None,
            }

    app.dependency_overrides[get_token_verifier] = UnverifiedTokenVerifier

    response = client.get(
        "/trial/me", headers={"Authorization": "Bearer unverified-token"}
    )

    assert response.status_code == 403


def test_trial_pdf_upload_counts_pages_and_persists_owner(trial_client):
    client, session_factory, _ = trial_client

    response = upload_pdf(client, pages=3)

    assert response.status_code == 200
    with session_factory() as session:
        uploaded = session.get(database.UploadedFile, response.json()["file_id"])
        assert uploaded.page_count == 3
        assert uploaded.owner_id == "verified-user"


def test_same_filename_reports_bind_and_meter_the_requested_file(
    trial_client, monkeypatch
):
    client, session_factory, _ = trial_client
    install_fast_pdf_analyzer(monkeypatch)
    first_file = upload_pdf(client, pages=1, filename="collision.pdf").json()["file_id"]
    second_file = upload_pdf(client, pages=3, filename="collision.pdf").json()["file_id"]

    first = client.post("/analyze", json={"file_id": first_file})
    second = client.post("/analyze", json={"file_id": second_file})

    assert first.status_code == second.status_code == 200
    with session_factory() as session:
        assert session.get(database.AccessibilityReport, first.json()["id"]).file_id == first_file
        assert session.get(database.AccessibilityReport, second.json()["id"]).file_id == second_file

    monkeypatch.setattr(main_module.PDFRemediator, "fix_all", lambda *args, **kwargs: [])
    response = client.post(
        "/remediate",
        json={"report_id": second.json()["id"], "apply_all_automatable": True},
    )

    assert response.status_code == 200
    with session_factory() as session:
        [job] = session.scalars(select(database.RemediationJob)).all()
        assert job.file_id == second_file
        assert job.page_count == 3
    assert client.get("/trial/me").json()["consumed_pages"] == 3


def test_same_filename_across_users_does_not_cross_bind_or_leak(
    trial_client, monkeypatch
):
    client, session_factory, _ = trial_client
    install_fast_pdf_analyzer(monkeypatch)
    active_user = {"id": "verified-user"}
    with session_factory() as session:
        session.add(database.User(id="other-user", email="other@gmail.com", name="Other"))
        session.commit()

    def current_user():
        with session_factory() as session:
            return session.get(database.User, active_user["id"])

    app.dependency_overrides[require_user] = current_user
    first_file = upload_pdf(client, pages=1, filename="shared.pdf").json()["file_id"]
    first_report = client.post("/analyze", json={"file_id": first_file}).json()["id"]
    active_user["id"] = "other-user"
    second_file = upload_pdf(client, pages=4, filename="shared.pdf").json()["file_id"]
    second_response = client.post("/analyze", json={"file_id": second_file})
    second_report = second_response.json()["id"]

    with session_factory() as session:
        assert session.get(database.AccessibilityReport, first_report).file_id == first_file
        assert session.get(database.AccessibilityReport, second_report).file_id == second_file

    monkeypatch.setattr(main_module.PDFRemediator, "fix_all", lambda *args, **kwargs: [])
    remediated = client.post(
        "/remediate",
        json={"report_id": second_report, "apply_all_automatable": True},
    )
    assert remediated.status_code == 200

    active_user["id"] = "verified-user"
    forbidden = client.post(
        "/remediate",
        json={"report_id": second_report, "apply_all_automatable": True},
    )

    assert forbidden.status_code == 403
    with session_factory() as session:
        [job] = session.scalars(select(database.RemediationJob)).all()
        assert job.user_id == "other-user"
        assert job.file_id == second_file
        assert job.page_count == 4


def test_upload_removes_partial_file_when_metadata_persistence_fails(
    trial_client, monkeypatch
):
    client, _, tmp_path = trial_client

    def fail_persistence(self, file_id, value):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(main_module.DbFileStorage, "__setitem__", fail_persistence)

    response = upload_pdf(client)

    assert response.status_code == 500
    assert response.json()["detail"] == "Unable to store uploaded file"
    assert list((tmp_path / "uploads").iterdir()) == []


def test_oversized_upload_stops_streaming_and_removes_staging_file(
    trial_client, monkeypatch
):
    _, session_factory, tmp_path = trial_client
    monkeypatch.setattr(settings, "MAX_FILE_SIZE_MB", 1)
    upload = CountingUpload(
        "large.pdf",
        [b"%PDF-" + b"a" * (1024 * 1024 - 5), b"more", b"must-not-be-read"],
    )
    with session_factory() as session:
        user = session.get(database.User, "verified-user")

    with pytest.raises(main_module.HTTPException) as exc_info:
        asyncio.run(main_module.upload_file(upload, user))

    assert exc_info.value.status_code == 400
    assert upload.read_calls == 2
    assert list((tmp_path / "uploads").rglob("*")) == []


def test_pdf_upload_validation_runs_via_threadpool_and_times_out(
    trial_client, monkeypatch
):
    _, session_factory, tmp_path = trial_client
    upload = CountingUpload("slow.pdf", [pdf_bytes(1), b""])
    monkeypatch.setattr(settings, "PDF_UPLOAD_VALIDATION_TIMEOUT_SECONDS", 0.01, raising=False)
    commands = []

    def timed_out(command, **kwargs):
        commands.append(command)
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(main_module.subprocess, "run", timed_out)
    with session_factory() as session:
        user = session.get(database.User, "verified-user")

    started = time.monotonic()
    with pytest.raises(main_module.HTTPException) as exc_info:
        asyncio.run(main_module.upload_file(upload, user))
    elapsed = time.monotonic() - started

    assert exc_info.value.status_code == 408
    assert "timed out" in exc_info.value.detail
    assert commands and commands[0][1:3] == ["-m", "backend.pdf_probe"]
    assert elapsed < 1
    assert list((tmp_path / "uploads").rglob("*")) == []


@pytest.mark.parametrize(
    ("filename", "content", "media_type"),
    [
        ("page.html", b"<html></html>", "text/html"),
        ("spoofed.pdf", b"<html>not a pdf</html>", "application/pdf"),
        ("broken.pdf", b"%PDF-1.7\nnot readable", "application/pdf"),
    ],
)
def test_trial_upload_rejects_non_pdf_or_malformed_pdf_without_persistence(
    trial_client, filename, content, media_type
):
    client, session_factory, tmp_path = trial_client

    response = client.post(
        "/upload", files={"file": (filename, content, media_type)}
    )

    assert response.status_code == 400
    assert "PDF" in response.json()["detail"]
    with session_factory() as session:
        assert session.query(database.UploadedFile).count() == 0
    assert list((tmp_path / "uploads").iterdir()) == []


def test_testing_mode_preserves_unmetered_html_upload(trial_client, monkeypatch):
    client, session_factory, _ = trial_client
    monkeypatch.setattr(settings, "DEPLOYMENT_MODE", "testing")

    response = client.post(
        "/upload", files={"file": ("page.html", b"<html></html>", "text/html")}
    )

    assert response.status_code == 200
    with session_factory() as session:
        assert session.query(database.TrialAccount).count() == 0
        assert session.query(database.TrialLedgerEntry).count() == 0
        assert session.query(database.RemediationJob).count() == 0


def test_testing_mode_remediation_is_unmetered_and_creates_no_trial_state(
    trial_client, monkeypatch
):
    client, session_factory, _ = trial_client
    monkeypatch.setattr(settings, "DEPLOYMENT_MODE", "testing")
    upload = upload_pdf(client, pages=2)
    report_id = seed_report(session_factory, upload.json()["file_id"], "testing-report")
    monkeypatch.setattr(main_module.PDFRemediator, "fix_all", lambda *args, **kwargs: [])

    response = client.post(
        "/remediate", json={"report_id": report_id, "apply_all_automatable": True}
    )

    assert response.status_code == 200
    with session_factory() as session:
        assert session.query(database.TrialAccount).count() == 0
        assert session.query(database.TrialLedgerEntry).count() == 0
        assert session.query(database.RemediationJob).count() == 0


def test_over_balance_rejected_before_pipeline_without_orphan_job(
    trial_client, monkeypatch
):
    client, session_factory, tmp_path = trial_client
    source = tmp_path / "uploads" / "large.pdf"
    source.write_bytes(pdf_bytes(1))
    with session_factory() as session:
        session.add(
            database.UploadedFile(
                id="large-file", filename="source.pdf", file_type="pdf",
                file_path=str(source), file_size=source.stat().st_size,
                page_count=201, owner_id="verified-user",
            )
        )
        session.commit()
    report_id = seed_report(session_factory, "large-file", "large-report")
    called = False

    def forbidden(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("pipeline must not run")

    monkeypatch.setattr(main_module.PDFRemediator, "fix_all", forbidden)

    response = client.post(
        "/remediate", json={"report_id": report_id, "apply_all_automatable": True}
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "trial_page_limit_exceeded",
        "requested_pages": 201,
        "remaining_pages": 200,
    }
    assert called is False
    with session_factory() as session:
        assert session.query(database.RemediationJob).count() == 0
        entries = session.scalars(select(database.TrialLedgerEntry)).all()
        assert [entry.entry_type for entry in entries] == ["grant"]


def test_successful_remediation_replays_without_rerun_or_double_charge(
    trial_client, monkeypatch
):
    client, session_factory, _ = trial_client
    upload = upload_pdf(client, pages=2)
    report_id = seed_report(session_factory, upload.json()["file_id"])
    calls = 0

    def successful_fix(*args, **kwargs):
        nonlocal calls
        calls += 1
        return []

    monkeypatch.setattr(main_module.PDFRemediator, "fix_all", successful_fix)

    first = client.post(
        "/remediate", json={"report_id": report_id, "apply_all_automatable": True}
    )
    duplicate = client.post(
        "/remediate", json={"report_id": report_id, "apply_all_automatable": True}
    )

    assert first.status_code == 200
    assert duplicate.status_code == 200
    assert duplicate.json() == first.json()
    assert calls == 1
    balance = client.get("/trial/me").json()
    assert balance["consumed_pages"] == 2
    assert balance["reserved_pages"] == 0
    assert balance["remaining_pages"] == 198
    with session_factory() as session:
        [job] = session.scalars(select(database.RemediationJob)).all()
        assert job.status == "succeeded"
        assert job.idempotency_key == "remediate:verified-user:report-1"
        assert job.response_json is not None
        output_key = ArtifactKey.parse(job.output_artifact_key)
        assert output_key.job_id == job.id
        assert output_key.kind == "remediated"
        assert not Path(job.output_artifact_key).is_absolute()
        assert app.state.artifact_store.download(
            "verified-user", job.output_artifact_key
        ).local_path.is_file()


def test_corrupt_succeeded_replay_is_safe_conflict_without_rerun(
    trial_client, monkeypatch
):
    client, session_factory, _ = trial_client
    upload = upload_pdf(client, pages=1)
    report_id = seed_report(session_factory, upload.json()["file_id"], "corrupt-replay")
    calls = 0

    def successful(*args, **kwargs):
        nonlocal calls
        calls += 1
        return []

    monkeypatch.setattr(main_module.PDFRemediator, "fix_all", successful)
    assert client.post("/remediate", json={"report_id": report_id}).status_code == 200
    with session_factory() as session:
        [job] = session.scalars(select(database.RemediationJob)).all()
        job.response_json = None
        session.commit()

    retry = client.post("/remediate", json={"report_id": report_id})

    assert retry.status_code == 409
    assert retry.json()["detail"]["code"] == "trial_remediation_state_invalid"
    assert calls == 1


def test_completion_failure_cleans_published_artifact_and_releases(
    trial_client, monkeypatch
):
    client, session_factory, _ = trial_client
    upload = upload_pdf(client, pages=1)
    report_id = seed_report(session_factory, upload.json()["file_id"], "complete-fail")
    monkeypatch.setattr(main_module.PDFRemediator, "fix_all", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        main_module.TrialService,
        "complete",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("commit failed")),
    )

    response = client.post("/remediate", json={"report_id": report_id})

    assert response.status_code == 500
    with session_factory() as session:
        [job] = session.scalars(select(database.RemediationJob)).all()
        assert job.status == "released"
        assert job.output_artifact_key is None
    jobs_root = settings.OUTPUT_DIR / "jobs"
    assert not jobs_root.exists() or list(jobs_root.iterdir()) == []


def test_cancelled_pipeline_releases_and_cleans_artifacts(trial_client, monkeypatch):
    _, session_factory, _ = trial_client
    content = pdf_bytes(1)
    source = settings.UPLOAD_DIR / "cancel.pdf"
    source.write_bytes(content)
    source_key = app.state.artifact_store.put(
        "verified-user", "cancel-file", "original", source, "cancel.pdf"
    )
    with session_factory() as session:
        session.add(database.UploadedFile(
            id="cancel-file", filename="cancel.pdf", file_type="pdf",
            file_path=source_key, file_size=len(content), page_count=1,
            owner_id="verified-user",
        ))
        session.commit()
    report_id = seed_report(session_factory, "cancel-file", "cancel-report")

    async def cancelled(*args, **kwargs):
        raise asyncio.CancelledError()

    monkeypatch.setattr(main_module, "run_in_threadpool", cancelled)
    with session_factory() as session:
        user = session.get(database.User, "verified-user")

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(main_module._remediate_trial(
            main_module.RemediationRequest(report_id=report_id),
            user,
            app.state.artifact_store,
        ))

    with session_factory() as session:
        [job] = session.scalars(select(database.RemediationJob)).all()
        assert job.status == "released"


def test_expired_processing_lease_is_recovered_on_trial_balance(
    trial_client
):
    client, session_factory, _ = trial_client
    with session_factory() as session:
        user = session.get(database.User, "verified-user")
        service = main_module.TrialService(session)
        service.ensure_account(user)
        job = database.RemediationJob(
            id="stale-api-job", user_id=user.id, status="pending", page_count=5,
            idempotency_key="stale-api-job",
        )
        session.add(job)
        now = datetime.now(timezone.utc)
        service.reserve_and_start_processing(
            user.id, job.id, 5, "stale-reserve", lease_seconds=1,
        )
        job.processing_started_at = now - timedelta(minutes=5)
        job.lease_expires_at = now - timedelta(minutes=1)
        session.commit()

    response = client.get("/trial/me")

    assert response.status_code == 200
    assert response.json()["remaining_pages"] == 200
    with session_factory() as session:
        assert session.get(database.RemediationJob, "stale-api-job").status == "released"


def test_duplicate_creation_integrity_race_does_not_run_pipeline(
    trial_client, monkeypatch
):
    client, session_factory, _ = trial_client
    upload = upload_pdf(client, pages=1)
    report_id = seed_report(session_factory, upload.json()["file_id"], "race-report")
    called = False

    def race(*args, **kwargs):
        raise IntegrityError("insert", {}, RuntimeError("duplicate"))

    def forbidden(*args, **kwargs):
        nonlocal called
        called = True
        return []

    monkeypatch.setattr(main_module.TrialService, "reserve_and_start_processing", race)
    monkeypatch.setattr(main_module.PDFRemediator, "fix_all", forbidden)

    response = client.post("/remediate", json={"report_id": report_id})

    assert response.status_code == 409
    assert called is False
    with session_factory() as session:
        assert session.query(database.RemediationJob).count() == 0


@pytest.mark.parametrize(
    "pipeline_error",
    [
        RuntimeError("secret internal path C:/sensitive/source.pdf"),
        TimeoutError("private timeout detail"),
    ],
)
def test_pipeline_failure_releases_once_and_restores_balance(
    trial_client, monkeypatch, pipeline_error
):
    client, session_factory, _ = trial_client
    upload = upload_pdf(client, pages=2)
    report_id = seed_report(session_factory, upload.json()["file_id"], "failed-report")

    def failed_fix(*args, **kwargs):
        raise pipeline_error

    monkeypatch.setattr(main_module.PDFRemediator, "fix_all", failed_fix)

    response = client.post(
        "/remediate", json={"report_id": report_id, "apply_all_automatable": True}
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "Remediation processing failed"
    assert client.get("/trial/me").json()["remaining_pages"] == 200
    with session_factory() as session:
        [job] = session.scalars(select(database.RemediationJob)).all()
        assert job.status == "released"
        assert "secret" not in job.failure_reason
        kinds = [
            row.entry_type
            for row in session.scalars(
                select(database.TrialLedgerEntry).where(
                    database.TrialLedgerEntry.job_id == job.id
                )
            ).all()
        ]
        assert kinds.count("release") == 1
    jobs_root = settings.OUTPUT_DIR / "jobs"
    assert not jobs_root.exists() or list(jobs_root.iterdir()) == []
    temp_root = settings.OUTPUT_DIR / ".tmp"
    assert not temp_root.exists() or list(temp_root.iterdir()) == []


def test_cross_user_same_filename_artifacts_and_downloads_are_isolated(
    trial_client, monkeypatch
):
    client, session_factory, _ = trial_client
    active_user = {"id": "verified-user"}
    with session_factory() as session:
        session.add(database.User(id="artifact-user", email="artifact@gmail.com", name="Artifact"))
        session.commit()

    def current_user():
        with session_factory() as session:
            return session.get(database.User, active_user["id"])

    app.dependency_overrides[require_user] = current_user
    first_bytes = pdf_bytes(1)
    first_upload = client.post(
        "/upload", files={"file": ("same.pdf", first_bytes, "application/pdf")}
    ).json()
    first_report = seed_report(session_factory, first_upload["file_id"], "artifact-report-1")
    active_user["id"] = "artifact-user"
    second_bytes = pdf_bytes(2)
    second_upload = client.post(
        "/upload", files={"file": ("same.pdf", second_bytes, "application/pdf")}
    ).json()
    second_report = seed_report(session_factory, second_upload["file_id"], "artifact-report-2")
    monkeypatch.setattr(main_module.PDFRemediator, "fix_all", lambda *args, **kwargs: [])

    second_result = client.post(
        "/remediate", json={"report_id": second_report, "apply_all_automatable": True}
    )
    second_download = client.get(f"/remediate/download/{second_report}")
    second_report_download = client.get(f"/remediate/report/{second_report}")
    active_user["id"] = "verified-user"
    first_result = client.post(
        "/remediate", json={"report_id": first_report, "apply_all_automatable": True}
    )
    first_download = client.get(f"/remediate/download/{first_report}")
    first_report_download = client.get(f"/remediate/report/{first_report}")
    forbidden = client.get(f"/remediate/download/{second_report}")
    forbidden_report = client.get(f"/remediate/report/{second_report}")

    assert first_result.status_code == second_result.status_code == 200
    assert first_download.content == first_bytes
    assert second_download.content == second_bytes
    assert first_download.content != second_download.content
    assert first_report_download.status_code == second_report_download.status_code == 200
    assert first_report_download.content.startswith(b"%PDF")
    assert second_report_download.content.startswith(b"%PDF")
    assert forbidden.status_code == 403
    assert forbidden_report.status_code == 403
    with session_factory() as session:
        jobs = session.scalars(select(database.RemediationJob)).all()
        assert len({job.output_artifact_key for job in jobs}) == 2


def test_path_traversal_display_filename_stays_inside_job_directory(
    trial_client, monkeypatch
):
    client, session_factory, tmp_path = trial_client
    upload = upload_pdf(client, pages=1, filename="../../escape.pdf")
    report_id = seed_report(session_factory, upload.json()["file_id"], "traversal-report")
    monkeypatch.setattr(main_module.PDFRemediator, "fix_all", lambda *args, **kwargs: [])

    response = client.post(
        "/remediate", json={"report_id": report_id, "apply_all_automatable": True}
    )

    assert response.status_code == 200
    with session_factory() as session:
        [job] = session.scalars(select(database.RemediationJob)).all()
        artifact_key = ArtifactKey.parse(job.output_artifact_key)
        assert artifact_key.job_id == job.id
        assert artifact_key.filename == "remediated_escape.pdf"
        assert app.state.artifact_store.download(
            "verified-user", job.output_artifact_key
        ).local_path.is_file()
    assert not (tmp_path / "escape.pdf").exists()


def test_heartbeat_keeps_tiny_lease_active_through_report_generation(
    trial_client, monkeypatch
):
    client, session_factory, _ = trial_client
    upload = upload_pdf(client, pages=1)
    report_id = seed_report(session_factory, upload.json()["file_id"], "heartbeat-report")
    report_started = threading.Event()
    monkeypatch.setattr(main_module, "_trial_lease_seconds", lambda: 0.3)
    monkeypatch.setattr(main_module, "_trial_heartbeat_interval", lambda lease: 0.05)
    monkeypatch.setattr(main_module.PDFRemediator, "fix_all", lambda *args, **kwargs: [])

    def slow_report(*, output_dir, **kwargs):
        report_started.set()
        time.sleep(0.45)
        path = Path(output_dir) / "report.pdf"
        path.write_bytes(b"%PDF-report")
        return path

    import backend.remediation_report as report_module
    monkeypatch.setattr(report_module, "generate_remediation_report_for_api", slow_report)

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(client.post, "/remediate", json={"report_id": report_id})
        assert report_started.wait(timeout=2)
        time.sleep(0.32)
        balance_during = client.get("/trial/me")
        result = future.result(timeout=3)

    assert balance_during.status_code == 200
    assert balance_during.json()["reserved_pages"] == 1
    assert result.status_code == 200
    with session_factory() as session:
        [job] = session.scalars(select(database.RemediationJob)).all()
        assert job.status == "succeeded"
