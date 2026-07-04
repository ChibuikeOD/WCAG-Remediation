"""API contract tests for trial balances, uploads, and metered remediation."""

import asyncio
from pathlib import Path

import fitz
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import backend.database as database
import backend.main as main_module
import backend.pdf_accessibility as pdf_accessibility_module
from backend.auth import get_token_verifier, require_user
from backend.config import settings
from backend.main import app
from backend.models import AccessibilityReport, DocumentInfo


def pdf_bytes(page_count=1):
    document = fitz.open()
    for _ in range(page_count):
        document.new_page()
    content = document.tobytes()
    document.close()
    return content


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

    async def idle_retention_worker():
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


def test_successful_remediation_consumes_exact_pages_and_duplicate_is_conflict(
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
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["code"] == "trial_remediation_conflict"
    assert calls == 1
    balance = client.get("/trial/me").json()
    assert balance["consumed_pages"] == 2
    assert balance["reserved_pages"] == 0
    assert balance["remaining_pages"] == 198
    with session_factory() as session:
        [job] = session.scalars(select(database.RemediationJob)).all()
        assert job.status == "succeeded"
        assert job.idempotency_key == "remediate:verified-user:report-1"


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
