"""Minimal killable subprocess probe for authoritative PDF page counts."""

import json
from pathlib import Path
import sys

import fitz


def probe_pdf(path: Path) -> int:
    document = fitz.open(path)
    try:
        page_count = document.page_count
    finally:
        document.close()
    if page_count <= 0:
        raise ValueError("PDF has no pages")
    return page_count


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if len(arguments) != 1:
        return 2
    try:
        page_count = probe_pdf(Path(arguments[0]))
    except Exception:
        return 2
    sys.stdout.write(json.dumps({"page_count": page_count}, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
