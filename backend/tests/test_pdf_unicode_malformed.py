from pathlib import Path
import pikepdf
import pytest
from backend import pdf_unicode_mapping as module
SAMPLE_CMAP = b"""begincmap
1 begincodespacerange
<0000> <FFFF>
endcodespacerange
1 beginbfchar
<0374> <0032>
endbfchar
endcmap
"""


def build_type0_pdf(path, shown_cid):
    with pikepdf.Pdf.new() as pdf:
        page = pdf.add_blank_page(page_size=(72, 72))
        descendant = pdf.make_indirect(pikepdf.Dictionary(
            Type=pikepdf.Name.Font, Subtype=pikepdf.Name.CIDFontType2,
            CIDToGIDMap=pikepdf.Name.Identity))
        font = pdf.make_indirect(pikepdf.Dictionary(
            Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type0,
            BaseFont=pikepdf.Name.TestFont, Encoding=pikepdf.Name('/Identity-H'),
            DescendantFonts=pikepdf.Array([descendant]),
            ToUnicode=pdf.make_stream(SAMPLE_CMAP)))
        page.Resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=font))
        page.Contents = pdf.make_stream(
            f'BT /F1 12 Tf <{shown_cid:04X}> Tj ET'.encode('ascii'))
        pdf.save(path)
    return path


def test_malformed_font_is_reported_without_rewriting_or_provider(tmp_path):
    path = build_type0_pdf(tmp_path / 'bad.pdf', 0x374)
    with pikepdf.open(path, allow_overwriting_input=True) as pdf:
        font = pdf.pages[0].Resources.Font.F1
        damaged = SAMPLE_CMAP.replace(b'<0032>', b'<D800>')
        font.ToUnicode.write(damaged)
        pdf.save(path)
    original = path.read_bytes()
    def forbidden(_context):
        raise AssertionError('malformed map must not reach provider')
    result = module.repair_missing_unicode(path, verifier=forbidden)
    assert result['details']['unresolved'] == 1
    assert result['details']['decisions'][0]['unresolved_reason'].startswith('malformed-to-unicode:')
    assert path.read_bytes() == original
    with pytest.raises(UnicodeError):
        module.parse_to_unicode_cmap(damaged)


def test_inventory_continues_other_font_and_parses_each_map_once(tmp_path, monkeypatch):
    path = build_type0_pdf(tmp_path / 'mixed.pdf', 0x375)
    with pikepdf.open(path, allow_overwriting_input=True) as pdf:
        page = pdf.pages[0]
        bad = pdf.make_indirect(pikepdf.Dictionary(page.Resources.Font.F1))
        bad.ToUnicode = pdf.make_stream(SAMPLE_CMAP.replace(b'<0032>', b'<D800>'))
        page.Resources.Font.F2 = bad
        page.Contents = pdf.make_stream(b'BT /F2 12 Tf <0374> Tj /F1 12 Tf <0375> Tj <0375> Tj ET')
        pdf.save(path)
    calls = []
    original = module.parse_to_unicode_cmap
    def parse(data):
        calls.append(data)
        return original(data)
    monkeypatch.setattr(module, 'parse_to_unicode_cmap', parse)
    findings = module.inventory_missing_unicode(path)
    assert len(calls) == 2
    assert [(f.cid, f.occurrence_count, bool(f.unresolved_reason)) for f in findings] == [
        (0x375, 2, False), (0x374, 1, True)]


def test_cff_cids_are_not_assumed_identity():
    with pikepdf.Pdf.new() as pdf:
        font = pikepdf.Dictionary(DescendantFonts=pikepdf.Array([
            pikepdf.Dictionary(Subtype=pikepdf.Name.CIDFontType0)]))
        assert module._font_gid(font, 2872) is None

def test_simple_font_codes_use_one_byte_without_cmap(tmp_path):
    path = tmp_path / 'simple.pdf'
    with pikepdf.Pdf.new() as pdf:
        page = pdf.add_blank_page(page_size=(72, 72))
        font = pdf.make_indirect(pikepdf.Dictionary(
            Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type1,
            BaseFont=pikepdf.Name.Helvetica))
        page.Resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=font))
        page.Contents = pdf.make_stream(b'BT /F1 12 Tf <3233> Tj ET')
        pdf.save(path)
    assert [f.cid for f in module.inventory_missing_unicode(path)] == [50, 51]
