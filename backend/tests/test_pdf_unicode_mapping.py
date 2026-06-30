from pathlib import Path

import pikepdf

from backend.pdf_unicode_mapping import (
    add_cmap_mappings,
    inventory_missing_unicode,
    parse_to_unicode_cmap,
)


SAMPLE_CMAP = b"""/CIDInit /ProcSet findresource begin
12 dict begin begincmap
/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def
/CMapName /Adobe-Identity-UCS def
/CMapType 2 def
1 begincodespacerange
<0000> <FFFF>
endcodespacerange
1 beginbfchar
<0374> <0032>
endbfchar
endcmap CMapName currentdict /CMap defineresource pop end end
"""


def build_type0_pdf(path: Path, shown_cid: int) -> Path:
    with pikepdf.Pdf.new() as pdf:
        page = pdf.add_blank_page(page_size=(72, 72))
        descriptor = pdf.make_indirect(
            pikepdf.Dictionary(
                Type=pikepdf.Name("/FontDescriptor"),
                FontName=pikepdf.Name("/TestFont"),
                Flags=4,
                FontBBox=pikepdf.Array([0, 0, 1000, 1000]),
                ItalicAngle=0,
                Ascent=800,
                Descent=-200,
                CapHeight=700,
                StemV=80,
            )
        )
        descendant = pdf.make_indirect(
            pikepdf.Dictionary(
                Type=pikepdf.Name("/Font"),
                Subtype=pikepdf.Name("/CIDFontType2"),
                BaseFont=pikepdf.Name("/TestFont"),
                CIDSystemInfo=pikepdf.Dictionary(
                    Registry="Adobe", Ordering="Identity", Supplement=0
                ),
                CIDToGIDMap=pikepdf.Name("/Identity"),
                FontDescriptor=descriptor,
            )
        )
        font = pdf.make_indirect(
            pikepdf.Dictionary(
                Type=pikepdf.Name("/Font"),
                Subtype=pikepdf.Name("/Type0"),
                BaseFont=pikepdf.Name("/TestFont"),
                Encoding=pikepdf.Name("/Identity-H"),
                DescendantFonts=pikepdf.Array([descendant]),
                ToUnicode=pdf.make_stream(SAMPLE_CMAP),
            )
        )
        page.Resources = pikepdf.Dictionary(
            Font=pikepdf.Dictionary(F1=font)
        )
        page.Contents = pdf.make_stream(
            f"BT /F1 12 Tf 10 50 Td <{shown_cid:04X}> Tj ET".encode("ascii")
        )
        pdf.save(path)
    return path


def test_inventory_finds_used_cid_missing_from_tounicode(tmp_path: Path) -> None:
    path = build_type0_pdf(tmp_path / "missing.pdf", shown_cid=0x0B36)

    findings = inventory_missing_unicode(path)

    assert len(findings) == 1
    finding = findings[0]
    assert finding.cid == 0x0B36
    assert finding.occurrence_count == 1
    assert finding.pages == (1,)


def test_inventory_ignores_mapped_cid(tmp_path: Path) -> None:
    path = build_type0_pdf(tmp_path / "mapped.pdf", shown_cid=0x0374)

    assert inventory_missing_unicode(path) == []


def test_cmap_round_trip_preserves_existing_entries() -> None:
    parsed = parse_to_unicode_cmap(SAMPLE_CMAP)

    updated = add_cmap_mappings(SAMPLE_CMAP, {0x0B36: "2"})
    reparsed = parse_to_unicode_cmap(updated)

    assert parsed.code_width == 2
    assert reparsed.mappings[0x0374] == "2"
    assert reparsed.mappings[0x0B36] == "2"
