"""Desktop behavior and privacy checks without any live provider credentials."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import fitz
import pytest

from backend.config import Settings, settings
from desktop.service import remediate_local

ROOT = Path(__file__).resolve().parents[2]


def test_local_mode_removes_inherited_cloud_credentials():
    local = Settings(_env_file=None, LOCAL_ONLY=True, GEMINI_API_KEY="fake-key",
                     DEEPSEEK_API_KEY="fake-key", AI_GATEWAY_API_KEY="fake-key",
                     SUPABASE_SECRET_KEY="fake-key", JEV_STRUCTURE_REFINEMENT_ENABLED=True,
                     JEV_GLYPH_CONSENSUS_ENABLED=True, PDF_UNICODE_LLM_ENABLED=True)
    assert local.GEMINI_API_KEY is None
    assert local.DEEPSEEK_API_KEY is None
    assert local.AI_GATEWAY_API_KEY is None
    assert local.SUPABASE_SECRET_KEY is None
    assert not local.PDF_UNICODE_LLM_ENABLED
    assert not local.JEV_STRUCTURE_REFINEMENT_ENABLED
    assert not local.JEV_GLYPH_CONSENSUS_ENABLED
    assert local.DISABLE_LAYOUTLM


def test_desktop_runtime_blocks_network_and_does_not_import_web_services(tmp_path):
    script = """
import os, socket, sys
from desktop.runtime import configure_runtime
configure_runtime()
assert 'GEMINI_API_KEY' not in os.environ
from backend.config import settings
assert settings.LOCAL_ONLY and not settings.PDF_UNICODE_LLM_ENABLED
assert 'backend.main' not in sys.modules
assert 'backend.auth' not in sys.modules
for operation in (lambda: socket.getaddrinfo('example.com', 443),
                  lambda: socket.socket().connect(('127.0.0.1', 80)),
                  lambda: socket.socket(socket.AF_INET, socket.SOCK_DGRAM).sendto(b'x', ('127.0.0.1', 9))):
    try:
        operation()
    except PermissionError:
        pass
    else:
        raise AssertionError('Network was not blocked')
"""
    result = subprocess.run([sys.executable, "-c", script], cwd=ROOT, capture_output=True,
                            text=True, env={**os.environ, "GEMINI_API_KEY": "fake-key",
                                            "LOCALAPPDATA": str(tmp_path)}, timeout=30)
    assert result.returncode == 0, result.stderr


def test_local_pipeline_preserves_source_and_publishes_review_outputs(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "LOCAL_ONLY", True)
    monkeypatch.setattr(settings, "PDF_UNICODE_LLM_ENABLED", False)
    monkeypatch.setattr(settings, "JEV_STRUCTURE_REFINEMENT_ENABLED", False)
    monkeypatch.setattr(settings, "JEV_GLYPH_CONSENSUS_ENABLED", False)
    # Unit test excludes external tools; the packaged-app smoke test exercises them.
    monkeypatch.setattr(settings, "DISABLE_OPENDATALOADER", True)
    source = tmp_path / "original.pdf"
    with fitz.open() as document:
        page = document.new_page()
        page.insert_text((72, 72), "Private local PDF")
        document.save(source)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    events = []
    result = remediate_local(source, tmp_path / "exports", events.append)
    assert result["cloud_ai_used"] is False
    assert result["processing"] == "on-device"
    assert result["review_required"] is True
    assert hashlib.sha256(source.read_bytes()).hexdigest() == digest
    with fitz.open(result["remediated_pdf"]) as repaired:
        assert repaired.metadata["title"] == "original"
        assert "Private local PDF" in repaired[0].get_text()
    with fitz.open(result["report_pdf"]) as report:
        assert report.page_count > 0
    output = Path(result["output_directory"])
    assert json.loads((output / "review.json").read_text())["before"]["total_issues"] > 0
    assert not list((tmp_path / "exports").glob(".pdfaccess-*"))
    assert "Complete" in events[-1]
    # Identical filenames are isolated into independent output folders on reruns.
    second = remediate_local(source, tmp_path / "exports")
    assert second["output_directory"] != result["output_directory"]


def test_failed_processing_removes_staging_and_does_not_publish(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "LOCAL_ONLY", True)
    source = tmp_path / "bad.pdf"
    with fitz.open() as document:
        document.new_page()
        document.save(source)
    def fail(_path):
        raise RuntimeError("analysis failed")
    monkeypatch.setattr("desktop.service.analyze_pdf", fail)
    with pytest.raises(RuntimeError, match="analysis failed"):
        remediate_local(source, tmp_path / "exports")
    assert list((tmp_path / "exports").iterdir()) == []


def test_local_pipeline_requires_privacy_configuration(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "LOCAL_ONLY", False)
    with pytest.raises(RuntimeError, match="privacy runtime"):
        remediate_local(tmp_path / "input.pdf", tmp_path)
