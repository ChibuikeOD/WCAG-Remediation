import fitz
import pikepdf
from unittest.mock import Mock

from backend.pdf_link_descriptions import repair_link_descriptions
from backend.pdf_link_descriptions import _word_inside_annotation
from backend.pdf_link_descriptions import _visible_label


def test_clickable_number_excludes_adjacent_punctuation():
    box = fitz.Rect(0, 0, 15, 10)
    characters = [{"c": text, "bbox": (index * 5, 0, (index + 1) * 5, 10)}
                  for index, text in enumerate("5.1:")]
    assert _visible_label(box, {"blocks": [{"lines": [{"spans": [{"chars": characters}]}]}]}) == "5.1"
    clipped = [{"c": text, "bbox": (index * 5, 0, (index + 1) * 5, 10)}
               for index, text in enumerate("Partial")]
    assert _visible_label(box, {"blocks": [{"lines": [{"spans": [{"chars": clipped}]}]}]}) == ""


def test_ink_rectangle_accepts_full_word_and_rejects_neighboring_line_or_partial_word():
    # Grounded D10 page 6 TOC annotation and extracted word geometry.
    box = fitz.Rect(71.004, 183.870, 142.856, 194.096)
    assert _word_inside_annotation(box, (72.0, 184.0978, 91.7107, 196.1008, "List"))
    assert not _word_inside_annotation(box, (72.0, 172.0948, 91.7107, 184.0978, "Previous"))
    assert not _word_inside_annotation(box, (130.0, 184.0978, 170.0, 196.1008, "Partial"))
    # Grounded page 1 mail link differs from text bounds by only 0.0005 pt.
    assert _word_inside_annotation(fitz.Rect(60, 683.312, 174.048, 696.9297),
                                   (60, 683.3115, 174.0477, 696.9297, "repository@umassd.edu"))


def test_injection_save_failure_closes_renderer(monkeypatch):
    from backend import pdf_remediator_fixes as fixes
    page = Mock()
    page.get_text.return_value = "https://example.org"
    page.search_for.return_value = [fitz.Rect(1, 1, 20, 10)]
    page.get_links.return_value = []
    document = Mock()
    document.__iter__ = Mock(return_value=iter([page]))
    document.save.side_effect = PermissionError("denied")
    monkeypatch.setattr(fixes.fitz, "open", lambda path: document)
    result = fixes.inject_link_annotations("unused.pdf")
    assert result["success"] is False
    document.close.assert_called_once()


def test_visible_description_preserves_content_and_reports_unknown(tmp_path):
    path = tmp_path / "links.pdf"
    with fitz.open() as document:
        page = document.new_page()
        page.insert_text((72, 72), "Research dataset")
        rectangle = page.search_for("Research dataset")[0]
        page.insert_link({"kind": fitz.LINK_URI, "from": rectangle, "uri": "https://example.org/data"})
        page.insert_link({"kind": fitz.LINK_URI, "from": fitz.Rect(300, 300, 340, 330), "uri": "https://example.org/unknown"})
        document.save(path)
    with fitz.open(path) as document:
        before = document[0].get_text(), document[0].get_pixmap().samples
    result = repair_link_descriptions(path)
    assert result["unresolved"] == 1
    assert result["success"] is False
    with pikepdf.open(path) as pdf:
        assert str(pdf.pages[0].Annots[0].Contents) == "Research dataset"
        assert "/Contents" not in pdf.pages[0].Annots[1]
    with fitz.open(path) as document:
        assert (document[0].get_text(), document[0].get_pixmap().samples) == before
    assert repair_link_descriptions(path)["unresolved"] == 1


def test_existing_description_and_explicit_link_alt_are_preserved(tmp_path):
    path = tmp_path / "semantic-links.pdf"
    with pikepdf.Pdf.new() as pdf:
        page = pdf.add_blank_page()
        annotations = [pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.Link,
                       Rect=pikepdf.Array([0, 0, 10, 10]))) for _ in range(3)]
        annotations[0].Contents = pikepdf.String("Existing destination description")
        annotations[2].Contents = pikepdf.String("Link")
        page.Annots = pikepdf.Array(annotations)
        root = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructTreeRoot))
        link = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem, S=pikepdf.Name.Link,
                    P=root, Alt=pikepdf.String("Supplementary measurements"),
                    K=pikepdf.Dictionary(Type=pikepdf.Name.OBJR, Obj=annotations[1])))
        root.K = pikepdf.Array([link])
        pdf.Root.StructTreeRoot = root
        pdf.save(path)
    result = repair_link_descriptions(path)
    assert result["unresolved"] == 1
    with pikepdf.open(path) as pdf:
        annotations = pdf.pages[0].Annots
        assert str(annotations[0].Contents) == "Existing destination description"
        assert str(annotations[1].Contents) == "Supplementary measurements"
        assert str(annotations[2].Contents) == "Link"  # unresolved evidence never fabricated
