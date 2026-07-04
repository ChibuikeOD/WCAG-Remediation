"""Tests for the killable PDF validation subprocess entry point."""

import json
from pathlib import Path
import subprocess
import sys

import fitz

from backend.pdf_probe import probe_pdf


def make_pdf(path: Path, pages: int = 2) -> None:
    document = fitz.open()
    for _ in range(pages):
        document.new_page()
    document.save(path)
    document.close()


def test_probe_pdf_returns_authoritative_page_count(tmp_path):
    path = tmp_path / "valid.pdf"
    make_pdf(path, 2)

    assert probe_pdf(path) == 2


def test_probe_cli_emits_bounded_json_and_rejects_invalid_pdf(tmp_path):
    valid = tmp_path / "valid.pdf"
    invalid = tmp_path / "invalid.pdf"
    make_pdf(valid, 1)
    invalid.write_bytes(b"%PDF-not-readable")

    success = subprocess.run(
        [sys.executable, "-m", "backend.pdf_probe", str(valid)],
        capture_output=True, text=True, check=False, timeout=5,
    )
    failure = subprocess.run(
        [sys.executable, "-m", "backend.pdf_probe", str(invalid)],
        capture_output=True, text=True, check=False, timeout=5,
    )

    assert success.returncode == 0
    assert json.loads(success.stdout) == {"page_count": 1}
    assert len(success.stdout) < 128
    assert failure.returncode != 0
    assert failure.stdout == ""
