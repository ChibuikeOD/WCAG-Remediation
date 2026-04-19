"""
Integration tests for the FastAPI endpoints.
"""
import pytest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from fastapi.testclient import TestClient
from backend.main import app


@pytest.fixture
def client():
    """Create a test client."""
    return TestClient(app)


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


if __name__ == '__main__':
    pytest.main([__file__, '-v'])





