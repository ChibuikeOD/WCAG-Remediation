from io import BytesIO

import fitz
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
import pikepdf
import pytest

from backend.pdf_cidset import repair_cidsets


def _font_program():
    builder = FontBuilder(1000, isTTF=True)
    names = [".notdef", "A", "B"]
    builder.setupGlyphOrder(names)
    builder.setupCharacterMap({65: "A", 66: "B"})
    builder.setupGlyf({name: TTGlyphPen(None).glyph() for name in names})
    builder.setupHorizontalMetrics({name: (600, 0) for name in names})
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    builder.setupNameTable({"familyName": "Test", "styleName": "Regular", "uniqueFontIdentifier": "Test",
                            "fullName": "Test", "psName": "Test"})
    builder.setupOS2(sTypoAscender=800, sTypoDescender=-200, usWinAscent=800, usWinDescent=200)
    builder.setupPost()
    output = BytesIO()
    builder.save(output)
    return output.getvalue()


def _fixture(path, mapping):
    with fitz.open() as document:
        document.new_page().insert_text((30, 40), "Stable visible text")
        document.save(path)
    with pikepdf.open(path, allow_overwriting_input=True) as pdf:
        descriptor = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.FontDescriptor,
                    FontName=pikepdf.Name("/ABCDEF+Test"), FontFile2=pdf.make_stream(_font_program()),
                    CIDSet=pdf.make_stream(b"\x80")))
        font = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Font, Subtype=pikepdf.Name.CIDFontType2,
                    BaseFont=pikepdf.Name("/ABCDEF+Test"), FontDescriptor=descriptor,
                    CIDToGIDMap=(pikepdf.Name.Identity if mapping is None else pdf.make_stream(mapping))))
        pdf.pages[0].Resources.Font.UnusedEmbedded = font
        font_bytes = descriptor.FontFile2.read_bytes()
        pdf.save(path)
    return font_bytes


@pytest.mark.parametrize("mapping,expected", [(None, b"\xe0"),
                          (b"\x00\x00\x00\x02\x00\x00\x00\x01", b"\xf0")])
def test_complete_cid_membership_includes_unused_and_notdef_mappings(tmp_path, mapping, expected):
    path = tmp_path / "font.pdf"
    original_font = _fixture(path, mapping)
    with fitz.open(path) as document:
        before = document[0].get_text(), document[0].get_pixmap().samples
    result = repair_cidsets(path)
    assert result["success"] is True
    assert result["new_value"] == "1 CIDSet streams"
    with pikepdf.open(path) as pdf:
        font = pdf.pages[0].Resources.Font.UnusedEmbedded
        assert font.FontDescriptor.CIDSet.read_bytes() == expected
        assert font.FontDescriptor.FontFile2.read_bytes() == original_font
        if mapping is not None:
            assert font.CIDToGIDMap.read_bytes() == mapping
    with fitz.open(path) as document:
        assert (document[0].get_text(), document[0].get_pixmap().samples) == before
    assert repair_cidsets(path)["new_value"] == "0 CIDSet streams"


@pytest.mark.parametrize("mapping", [b"\x00", b"\x00\x04", b""])
def test_invalid_mapping_remains_explicitly_unresolved(tmp_path, mapping):
    path = tmp_path / "invalid.pdf"
    _fixture(path, mapping)
    original = path.read_bytes()
    result = repair_cidsets(path)
    assert result["success"] is False
    assert result["details"]["unresolved"]
    assert path.read_bytes() == original


def test_direct_descendant_font_is_included(tmp_path):
    path = tmp_path / "direct-descendant.pdf"
    _fixture(path, None)
    with pikepdf.open(path, allow_overwriting_input=True) as pdf:
        fonts = pdf.pages[0].Resources.Font
        child = pikepdf.Dictionary(fonts.UnusedEmbedded)
        del fonts.UnusedEmbedded
        fonts.Composite = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Font,
                            Subtype=pikepdf.Name.Type0, Encoding=pikepdf.Name("/Identity-H"),
                            DescendantFonts=pikepdf.Array([child])))
        pdf.save(path)
    assert repair_cidsets(path)["new_value"] == "1 CIDSet streams"
    with pikepdf.open(path) as pdf:
        assert pdf.pages[0].Resources.Font.Composite.DescendantFonts[0].FontDescriptor.CIDSet.read_bytes() == b"\xe0"


def test_unsupported_font_program_preserves_cidset(tmp_path):
    path = tmp_path / "unsupported.pdf"
    _fixture(path, None)
    with pikepdf.open(path, allow_overwriting_input=True) as pdf:
        pdf.pages[0].Resources.Font.UnusedEmbedded.Subtype = pikepdf.Name.CIDFontType0
        pdf.save(path)
    original = path.read_bytes()
    result = repair_cidsets(path)
    assert result["success"] is False
    assert "not supported" in result["details"]["unresolved"][0]["reason"]
    assert path.read_bytes() == original
