"""
Integration tests for the FastAPI endpoints.
"""
import asyncio
import os
import pytest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import backend.database as database
import backend.main as main_module
from backend.main import app, report_storage, settings
from backend.models import AccessibilityReport, DocumentInfo


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Create a test client with isolated storage and lifespan running."""
    test_engine = create_engine(
        f"sqlite:///{tmp_path / 'test.db'}",
        connect_args={"check_same_thread": False},
    )
    test_session_local = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=test_engine,
    )
    upload_dir = tmp_path / "uploads"
    output_dir = tmp_path / "output"
    upload_dir.mkdir()
    output_dir.mkdir()

    monkeypatch.setattr(database, "engine", test_engine)
    monkeypatch.setattr(database, "SessionLocal", test_session_local)
    monkeypatch.setattr(main_module, "SessionLocal", test_session_local)
    monkeypatch.setattr(settings, "UPLOAD_DIR", upload_dir)
    monkeypatch.setattr(settings, "OUTPUT_DIR", output_dir)

    async def idle_retention_worker():
        await asyncio.Event().wait()

    monkeypatch.setattr(main_module, "clean_expired_documents", idle_retention_worker)

    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        test_engine.dispose()


def test_client_uses_isolated_storage(client, tmp_path):
    assert Path(str(database.engine.url.database)).parent == tmp_path
    assert settings.UPLOAD_DIR == tmp_path / "uploads"
    assert settings.OUTPUT_DIR == tmp_path / "output"


class TestHealthEndpoint:
    """Tests for the health check endpoint."""
    
    def test_health_check(self, client):
        """Test that health endpoint returns healthy status."""
        response = client.get('/health')
        assert response.status_code == 200
        
        data = response.json()
        assert data['status'] == 'healthy'
        assert data['rules_loaded'] > 0


class TestRulesEndpoint:
    """Tests for the rules endpoint."""
    
    def test_list_all_rules(self, client):
        """Test listing all rules."""
        response = client.get('/rules')
        assert response.status_code == 200
        
        data = response.json()
        assert 'total' in data
        assert 'rules' in data
        assert data['total'] > 0
    
    def test_filter_rules_by_level(self, client):
        """Test filtering rules by WCAG level."""
        response = client.get('/rules?level=A')
        assert response.status_code == 200
        
        data = response.json()
        assert all(r['wcag_level'] == 'A' for r in data['rules'])
    
    def test_filter_rules_by_automatable(self, client):
        """Test filtering automatable rules."""
        response = client.get('/rules?automatable=true')
        assert response.status_code == 200
        
        data = response.json()
        assert all(r['automatable'] is True for r in data['rules'])
    
    def test_get_specific_rule(self, client):
        """Test getting a specific rule by ID."""
        response = client.get('/rules/1.1.1')
        assert response.status_code == 200
        
        data = response.json()
        assert data['id'] == '1.1.1'
        assert data['name'] == 'Non-text Content'
    
    def test_rule_not_found(self, client):
        """Test 404 for non-existent rule."""
        response = client.get('/rules/99.99.99')
        assert response.status_code == 404


class TestUploadEndpoint:
    """Tests for the upload endpoint."""
    
    def test_upload_html_file(self, client):
        """Test uploading an HTML file."""
        html_content = b"""
        <!DOCTYPE html>
        <html lang="en">
        <head><title>Test</title></head>
        <body><p>Hello</p></body>
        </html>
        """
        
        response = client.post(
            '/upload',
            files={'file': ('test.html', html_content, 'text/html')}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert data['file_id'] is not None
        assert data['file_type'] == 'html'
    
    def test_upload_invalid_file_type(self, client):
        """Test rejecting invalid file types."""
        response = client.post(
            '/upload',
            files={'file': ('test.txt', b'Hello World', 'text/plain')}
        )
        
        assert response.status_code == 400
        assert 'Unsupported file type' in response.json()['detail']


class TestAnalyzeEndpoint:
    """Tests for the analyze endpoint."""
    
    def test_analyze_uploaded_file(self, client):
        """Test analyzing an uploaded file."""
        # First upload a file
        html_content = b"""
        <!DOCTYPE html>
        <html lang="en">
        <head><title>Test Page</title></head>
        <body>
            <img src="test.jpg">
            <p>Hello World</p>
        </body>
        </html>
        """
        
        upload_response = client.post(
            '/upload',
            files={'file': ('test.html', html_content, 'text/html')}
        )
        file_id = upload_response.json()['file_id']
        
        # Then analyze it
        analyze_response = client.post(
            '/analyze',
            json={'file_id': file_id, 'target_level': 'AA'}
        )
        
        assert analyze_response.status_code == 200
        data = analyze_response.json()
        
        assert 'id' in data
        assert 'document' in data
        assert 'total_issues' in data
        assert 'all_issues' in data
        
        # Should detect missing alt attribute
        alt_issues = [i for i in data['all_issues'] if 'alt' in i['message'].lower()]
        assert len(alt_issues) > 0
    
    def test_analyze_missing_file(self, client):
        """Test analyzing a non-existent file."""
        response = client.post(
            '/analyze',
            json={'file_id': 'non-existent-id'}
        )
        
        assert response.status_code == 404
    
    def test_analyze_no_params(self, client):
        """Test analyze with no file_id or url."""
        response = client.post(
            '/analyze',
            json={}
        )
        
        assert response.status_code == 400


class TestReportEndpoint:
    """Tests for report retrieval endpoints."""
    
    def test_report_not_found(self, client):
        """Test 404 for non-existent report."""
        response = client.get('/report/non-existent-id')
        assert response.status_code == 404
    
    def test_report_summary_not_found(self, client):
        """Test 404 for non-existent report summary."""
        response = client.get('/report/non-existent-id/summary')
        assert response.status_code == 404


class TestRemediationDownloadEndpoint:
    """Tests for remediated file downloads."""

    def test_pdf_download_uses_pdf_media_type(self, client, tmp_path, monkeypatch):
        """PDF downloads should be served as PDFs, not generic binary blobs."""
        monkeypatch.setattr(settings, "OUTPUT_DIR", tmp_path)
        filename = "sample.pdf"
        report_id = "download-media-type-report"
        (tmp_path / f"remediated_{filename}").write_bytes(b"%PDF-1.4\n%%EOF\n")

        report_storage[report_id] = AccessibilityReport(
            id=report_id,
            document=DocumentInfo(filename=filename, file_type="pdf"),
        )

        response = client.get(f"/remediate/download/{report_id}")

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/pdf")


class TestRemediationReportDownloadEndpoint:
    """Tests for authenticated remediation-report downloads."""

    @staticmethod
    def _seed_report(report_id, owner_id="dev_user_001"):
        db = main_module.SessionLocal()
        try:
            db.add(database.User(id=owner_id, email=f"{owner_id}@example.com", name=owner_id))
            uploaded_file = database.UploadedFile(
                id=f"file-{report_id}",
                filename="source.pdf",
                file_type="pdf",
                file_path="unused/source.pdf",
                file_size=1,
                owner_id=owner_id,
            )
            db.add(uploaded_file)
            db.add(database.AccessibilityReport(
                id=report_id,
                file_id=uploaded_file.id,
                report_json="{}",
            ))
            db.commit()
        finally:
            db.close()

    def test_download_remediation_report_returns_latest_pdf(self, client):
        report_id = "owned-report"
        self._seed_report(report_id)
        older = settings.OUTPUT_DIR / f"Remediation_Report_{report_id}_older.pdf"
        latest = settings.OUTPUT_DIR / f"Remediation_Report_{report_id}_latest.pdf"
        older.write_bytes(b"older")
        latest.write_bytes(b"latest")
        os.utime(older, (1, 1))
        os.utime(latest, (2, 2))

        response = client.get(f"/remediate/report/{report_id}")

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/pdf")
        assert response.headers["content-disposition"] == f'attachment; filename="{latest.name}"'
        assert response.content == b"latest"

    def test_download_remediation_report_returns_404_without_artifact(self, client):
        report_id = "report-without-artifact"
        self._seed_report(report_id)

        response = client.get(f"/remediate/report/{report_id}")

        assert response.status_code == 404
        assert response.json()["detail"] == "Remediation report not found"

    def test_download_remediation_report_rejects_another_users_report(self, client):
        report_id = "another-users-report"
        self._seed_report(report_id, owner_id="another-user")
        (settings.OUTPUT_DIR / f"Remediation_Report_{report_id}_result.pdf").write_bytes(b"private")

        response = client.get(f"/remediate/report/{report_id}")

        assert response.status_code == 403

    def test_download_remediation_report_returns_404_for_orphaned_report(self, client):
        report_id = "orphaned-report"
        db = main_module.SessionLocal()
        try:
            db.add(database.AccessibilityReport(
                id=report_id,
                file_id="missing-file",
                report_json="{}",
            ))
            db.commit()
        finally:
            db.close()
        (settings.OUTPUT_DIR / f"Remediation_Report_{report_id}_result.pdf").write_bytes(b"orphaned")

        response = client.get(f"/remediate/report/{report_id}")

        assert response.status_code == 404

    def test_download_remediation_report_rejects_ownerless_report(self, client):
        report_id = "ownerless-report"
        db = main_module.SessionLocal()
        try:
            uploaded_file = database.UploadedFile(
                id=f"file-{report_id}",
                filename="source.pdf",
                file_type="pdf",
                file_path="unused/source.pdf",
                file_size=1,
                owner_id=None,
            )
            db.add(uploaded_file)
            db.add(database.AccessibilityReport(
                id=report_id,
                file_id=uploaded_file.id,
                report_json="{}",
            ))
            db.commit()
        finally:
            db.close()
        (settings.OUTPUT_DIR / f"Remediation_Report_{report_id}_result.pdf").write_bytes(b"ownerless")

        response = client.get(f"/remediate/report/{report_id}")

        assert response.status_code == 403


if __name__ == '__main__':
    pytest.main([__file__, '-v'])





