import copy
import hashlib
import json

import fitz
import pikepdf
import pytest

from backend.pdf_reviewed_glyphs import _fingerprint, load_reviewed_glyphs
from backend.pdf_unicode_mapping import repair_missing_unicode, parse_to_unicode_cmap


def fixture(tmp_path):
    original = tmp_path / "original.pdf"
    with pikepdf.Pdf.new() as pdf:
        page = pdf.add_blank_page(page_size=(200, 200))
        proc = pdf.make_stream(b"600 0 0 0 600 700 d1 0 0 500 700 re f")
        font = pdf.make_indirect(pikepdf.Dictionary(
            Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type3,
            FontBBox=pikepdf.Array([0, 0, 600, 700]),
            FontMatrix=pikepdf.Array([.001, 0, 0, .001, 0, 0]),
            CharProcs=pikepdf.Dictionary(a114=proc),
            Encoding=pikepdf.Dictionary(Differences=pikepdf.Array([114, pikepdf.Name('/a114')])),
            FirstChar=114, LastChar=114, Widths=pikepdf.Array([600]), Resources=pikepdf.Dictionary()))
        page.Resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(F16=font))
        page.Contents = pdf.make_stream(b"BT /F16 20 Tf 20 60 Td (r) Tj ET")
        pdf.save(original)
    with pikepdf.open(original) as pdf:
        font = pdf.pages[0].Resources.Font.F16
        binding = dict(source_id="original", input_sha256=hashlib.sha256(original.read_bytes()).hexdigest(),
                       font_objgen=list(font.objgen), font_resource="/F16", font_fingerprint_sha256=_fingerprint(font),
                       font_encoding_sha256=hashlib.sha256(font.Encoding.unparse()).hexdigest(),
                       character_code=114, glyph_name="/a114",
                       decoded_charproc_sha256=hashlib.sha256(font.CharProcs.a114.read_bytes()).hexdigest())
        source = dict(binding, font_matrix=[float(x) for x in font.FontMatrix], font_bbox=[float(x) for x in font.FontBBox])
    data = dict(schema_version="pdfaccess.glyph-proposals.v1", review_status="REVIEWED", sources=[source],
                proposals=[dict(review_status="REVIEWED", proposed_unicode="r", proposal_id="review-r", bindings=[binding])])
    sidecar = tmp_path / 'review.json'
    sidecar.write_text(json.dumps(data), encoding='utf-8')
    return original, sidecar, data


def test_repair_exact_reviewed_type3_without_cmap_preserves_pixels_and_program(tmp_path):
    original, sidecar, _ = fixture(tmp_path)
    target = tmp_path / 'working.pdf'
    target.write_bytes(original.read_bytes())
    with fitz.open(original) as pdf:
        pixels = pdf[0].get_pixmap(dpi=96).samples
    result = repair_missing_unicode(target, reviewed_glyph_sidecar=sidecar, reviewed_glyph_original=original)
    assert result['success']
    assert result['details']['reviewed_sidecar_applied'] == 1
    assert result['details']['total_mappings_applied'] == 1
    assert result['details']['font_metadata_applied'] == 0
    assert result['details']['verified_local_font_applied'] == 0
    assert result['details']['provider'] is None
    assert result['details']['external_provider_status'] == 'not-invoked'
    assert not result['details']['external_verifier_configured']
    assert '1 model-reviewed sidecar mapping(s)' in result['message']
    assert 'No external Unicode verifier was invoked.' in result['message']
    assert 'requested but unavailable' not in result['message']
    decision = result['details']['decisions'][0]
    assert decision['resolution_source'] == 'model-reviewed-sidecar'
    assert not decision['llm_invoked']
    assert not decision['reviewed_glyph_evidence']['font_metadata_authority']
    with pikepdf.open(original) as before, pikepdf.open(target) as after:
        a, b = before.pages[0].Resources.Font.F16, after.pages[0].Resources.Font.F16
        assert _fingerprint(a) == _fingerprint(b)
        assert a.Encoding.unparse() == b.Encoding.unparse()
        assert parse_to_unicode_cmap(b.ToUnicode.read_bytes()).mappings == {114:'r'}
    with fitz.open(target) as pdf:
        assert pdf[0].get_pixmap(dpi=96).samples == pixels
        assert pdf[0].get_text().strip() == 'r'


@pytest.mark.parametrize('field,value', [('input_sha256','0'*64), ('decoded_charproc_sha256','0'*64),
    ('font_fingerprint_sha256','0'*64), ('font_encoding_sha256','0'*64), ('character_code',115)])
def test_tampered_evidence_rejected_without_pdf_mutation(tmp_path, field, value):
    original, sidecar, data = fixture(tmp_path)
    original_bytes = original.read_bytes()
    data['proposals'][0]['bindings'][0][field] = value
    sidecar.write_text(json.dumps(data), encoding='utf-8')
    with pytest.raises(ValueError):
        load_reviewed_glyphs(sidecar, original, original)
    assert original.read_bytes() == original_bytes


def test_conflicts_rejected(tmp_path):
    original, sidecar, data = fixture(tmp_path)
    other = copy.deepcopy(data['proposals'][0]); other['proposed_unicode'] = 's'
    data['proposals'].append(other)
    sidecar.write_text(json.dumps(data), encoding='utf-8')
    with pytest.raises(ValueError, match='conflicting'):
        load_reviewed_glyphs(sidecar, original, original)


def test_changed_working_glyph_is_unmatched(tmp_path):
    original, sidecar, _ = fixture(tmp_path)
    target = tmp_path / 'changed.pdf'
    with pikepdf.open(original) as pdf:
        pdf.pages[0].Resources.Font.F16.CharProcs.a114.write(b'600 0 0 0 600 700 d1')
        pdf.save(target)
    assert load_reviewed_glyphs(sidecar, original, target) == {}


def test_existing_unicode_conflict_is_rejected(tmp_path):
    original, sidecar, _ = fixture(tmp_path)
    target = tmp_path / 'conflict.pdf'
    with pikepdf.open(original) as pdf:
        pdf.pages[0].Resources.Font.F16.ToUnicode = pdf.make_stream(
            b'1 begincodespacerange <00> <FF> endcodespacerange 1 beginbfchar <72> <0073> endbfchar endcmap')
        pdf.save(target)
    before = target.read_bytes()
    with pytest.raises(ValueError, match='conflicts with existing'):
        load_reviewed_glyphs(sidecar, original, target)
    assert target.read_bytes() == before


def test_other_original_sha_and_unreviewed_sidecar_are_rejected(tmp_path):
    original, sidecar, data = fixture(tmp_path)
    other = tmp_path / 'other.pdf'; other.write_bytes(original.read_bytes() + b'\n')
    with pytest.raises(ValueError, match='original document SHA256'):
        load_reviewed_glyphs(sidecar, other, original)
    data['review_status'] = 'PENDING'
    sidecar.write_text(json.dumps(data), encoding='utf-8')
    with pytest.raises(ValueError, match='unreviewed'):
        load_reviewed_glyphs(sidecar, original, original)


def test_reviewed_rollback_reports_zero_applied(tmp_path, monkeypatch):
    from backend import pdf_unicode_mapping as module
    original, sidecar, _ = fixture(tmp_path)
    target = tmp_path / 'rollback.pdf'; target.write_bytes(original.read_bytes())
    monkeypatch.setattr(module, 'verify_repair', lambda *_: (False, 'visual-diff'))
    result = repair_missing_unicode(target, reviewed_glyph_sidecar=sidecar, reviewed_glyph_original=original)
    assert not result['success']
    assert result['details']['reviewed_sidecar_applied'] == 0
    assert result['details']['total_mappings_applied'] == 0
    assert target.read_bytes() == original.read_bytes()
