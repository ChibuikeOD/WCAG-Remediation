import hashlib
import json

import pikepdf

from backend.pdf_reviewed_glyphs import _encoding_content, load_reviewed_glyphs
from backend.pdf_unicode_mapping import repair_missing_unicode, parse_to_unicode_cmap
from backend.remediator import PDFRemediator
from backend.tests.test_pdf_reviewed_glyphs import fixture


def indirect_fixture(tmp_path):
    source, sidecar, data = fixture(tmp_path)
    original = tmp_path / 'indirect-original.pdf'
    with pikepdf.open(source) as pdf:
        font = pdf.pages[0].Resources.Font.F16
        font.Encoding = pdf.make_indirect(font.Encoding)
        pdf.save(original)
    with pikepdf.open(original) as pdf:
        font = pdf.pages[0].Resources.Font.F16
        binding = data['proposals'][0]['bindings'][0]
        binding['font_objgen'] = list(font.objgen)
        binding['input_sha256'] = hashlib.sha256(original.read_bytes()).hexdigest()
        binding['font_encoding_sha256'] = hashlib.sha256(font.Encoding.unparse()).hexdigest()
        data['sources'][0].update(binding)
    sidecar.write_text(json.dumps(data), encoding='utf-8')
    return original, sidecar


def test_actual_metadata_rewrite_keeps_semantic_encoding_binding(tmp_path):
    original, sidecar = indirect_fixture(tmp_path)
    before = original.read_bytes()
    working = tmp_path / 'working.pdf'; working.write_bytes(before)
    results = PDFRemediator(working).fix_metadata(title='Bound glyph fixture', language='en-US')
    assert all(r.success for r in results)
    with pikepdf.open(original) as old, pikepdf.open(working) as new:
        a,b = old.pages[0].Resources.Font.F16,new.pages[0].Resources.Font.F16
        assert a.Encoding.unparse() != b.Encoding.unparse()
        assert _encoding_content(a) == _encoding_content(b)
    assert len(load_reviewed_glyphs(sidecar, original, working)) == 1
    result = repair_missing_unicode(working, reviewed_glyph_sidecar=sidecar, reviewed_glyph_original=original)
    assert result['success'] and result['details']['reviewed_sidecar_applied'] == 1
    with pikepdf.open(working) as pdf:
        assert parse_to_unicode_cmap(pdf.pages[0].Resources.Font.F16.ToUnicode.read_bytes()).mappings == {114:'r'}
    assert original.read_bytes() == before


def test_different_encoding_values_do_not_bind_after_rewrite(tmp_path):
    original, sidecar = indirect_fixture(tmp_path)
    working = tmp_path / 'different.pdf'
    with pikepdf.open(original) as pdf:
        pdf.pages[0].Resources.Font.F16.Encoding.BaseEncoding = pikepdf.Name.WinAnsiEncoding
        pdf.save(working)
    assert load_reviewed_glyphs(sidecar, original, working) == {}
