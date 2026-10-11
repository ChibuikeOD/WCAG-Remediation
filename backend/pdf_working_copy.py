"""Create writable task-owned bytes without copying immutable input attributes."""
from pathlib import Path
import shutil


def create_pdf_working_copy(source: Path, destination: Path) -> Path:
    source, destination = Path(source), Path(destination)
    # Exclusive creation also rejects an existing destination symlink or source.
    with source.open("rb") as reader:
        with destination.open("xb") as writer:
            shutil.copyfileobj(reader, writer)
    return destination
