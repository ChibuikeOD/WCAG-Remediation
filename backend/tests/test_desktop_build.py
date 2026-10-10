from pathlib import Path
import zipfile

import pytest

from scripts.build_desktop import extract, validate_bundle


def test_runtime_archive_cannot_write_outside_staging(tmp_path):
    archive = tmp_path / "runtime.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("../escape.txt", "must not escape")
    with pytest.raises(ValueError, match="escapes"):
        extract(archive, tmp_path / "staging")
    assert not (tmp_path / "escape.txt").exists()


@pytest.mark.parametrize("private_file", ["input.pdf", "state.db", ".env", ".env.production"])
def test_download_cannot_contain_documents_databases_or_env_files(tmp_path, private_file):
    archive = tmp_path / "app.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("PDFAccess/PDFAccess.exe", "synthetic app")
        zipped.writestr(f"PDFAccess/_internal/{private_file}", "private")
    with pytest.raises(RuntimeError, match="private/generated"):
        validate_bundle(archive)


def test_download_requires_the_executable(tmp_path):
    archive = tmp_path / "app.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("PDFAccess/README.md", "usage")
    with pytest.raises(RuntimeError, match="missing its executable"):
        validate_bundle(archive)
