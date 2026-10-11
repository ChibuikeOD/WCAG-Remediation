from unittest.mock import Mock

import fitz
import pikepdf
import pytest

from backend import pdf_remediator_fixes as fixes


@pytest.mark.parametrize("operation", ["get_toc", "set_toc", "save"])
def test_bookmark_failure_always_closes_reader(monkeypatch, operation):
    document = Mock()
    document.get_toc.return_value = []
    document.__iter__ = Mock(return_value=iter(()))
    getattr(document, operation).side_effect = RuntimeError(f"failed {operation}")
    monkeypatch.setattr(fixes.fitz, "open", lambda path: document)
    monkeypatch.setattr(fixes, "HAS_PIKEPDF", False)
    result = fixes.fix_bookmarks("unused.pdf")
    assert result["success"] is False
    document.close.assert_called_once()


def test_skipped_heading_levels_produce_valid_bookmarks_and_release_file(tmp_path):
    path = tmp_path / "headings.pdf"
    with fitz.open() as document:
        page = document.new_page(width=300, height=300)
        for line, level in enumerate((4, 6, 2, 5)):
            page.insert_text((30, 40 + line * 30), f"Heading {level}")
        document.save(path)
    with pikepdf.open(path, allow_overwriting_input=True) as pdf:
        page = pdf.pages[0]
        root = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructTreeRoot))
        document = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem, S=pikepdf.Name.Document, P=root))
        root.K = pikepdf.Array([document])
        document.K = pikepdf.Array([
            pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem, S=pikepdf.Name(f"/H{level}"),
                                               T=f"Heading {level}", P=document, Pg=page.obj))
            for level in (4, 6, 2, 5)
        ])
        pdf.Root.StructTreeRoot = root
        pdf.save(path)
    with fitz.open(path) as before:
        pixels = before[0].get_pixmap().samples
        text = before[0].get_text()
    result = fixes.fix_bookmarks(path)
    assert result["success"] is True
    with fitz.open(path) as after:
        assert [row[0] for row in after.get_toc()] == [1, 2, 2, 3]
        assert after[0].get_pixmap().samples == pixels
        assert after[0].get_text() == text
    # Exercise the exact subsequent writer that previously failed on Windows.
    with pikepdf.open(path, allow_overwriting_input=True) as pdf:
        pdf.pages[0].obj.Tabs = pikepdf.Name.S
        pdf.save(path)
