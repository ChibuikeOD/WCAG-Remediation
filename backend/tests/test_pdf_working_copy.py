import hashlib
import stat

import pytest

from backend.pdf_working_copy import create_pdf_working_copy


def test_readonly_input_remains_immutable_and_copy_is_writable(tmp_path):
    source, destination = tmp_path / "original.pdf", tmp_path / "working.pdf"
    source.write_bytes(b"%PDF-1.7\nimmutable public input\n")
    source.chmod(stat.S_IREAD)
    original = source.stat()
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    try:
        create_pdf_working_copy(source, destination)
        assert destination.read_bytes() == source.read_bytes()
        with destination.open("r+b") as working:
            working.write(b"%PDF-1.7\nwritable remediation\n")
        assert hashlib.sha256(source.read_bytes()).hexdigest() == digest
        assert source.stat().st_mode == original.st_mode
        assert source.stat().st_mtime_ns == original.st_mtime_ns
        if hasattr(original, "st_file_attributes"):
            assert source.stat().st_file_attributes == original.st_file_attributes
    finally:
        # Only the disposable test-owned fixture is restored for pytest cleanup.
        source.chmod(stat.S_IREAD | stat.S_IWRITE)


def test_existing_destination_and_source_are_never_overwritten(tmp_path):
    source, destination = tmp_path / "original.pdf", tmp_path / "existing.pdf"
    source.write_bytes(b"source")
    destination.write_bytes(b"existing")
    for target in (source, destination):
        with pytest.raises(FileExistsError):
            create_pdf_working_copy(source, target)
    assert source.read_bytes() == b"source"
    assert destination.read_bytes() == b"existing"
