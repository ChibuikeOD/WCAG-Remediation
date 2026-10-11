import fitz

from backend import config, pdf_remediator_fixes
from backend.remediation_report import generate_remediation_report_for_api
from backend.tests.test_pdf_reviewed_glyph_rewrite import indirect_fixture


def test_actual_wrapper_and_report_do_not_claim_external_provider_use(tmp_path, monkeypatch):
    original, sidecar = indirect_fixture(tmp_path)
    working = tmp_path / 'working.pdf'; working.write_bytes(original.read_bytes())
    monkeypatch.setattr(config.settings, 'PDF_UNICODE_LLM_ENABLED', False)
    result = pdf_remediator_fixes.fix_pdf_unicode_mappings(
        working, reviewed_glyph_sidecar=sidecar, reviewed_glyph_original=original)
    assert result['success']
    details = result['details']
    assert details['total_mappings_applied'] == details['reviewed_sidecar_applied'] == 1
    assert details['applied'] == 0 and not details['llm_invoked']
    assert not details['llm_unavailable']
    assert details['provider'] is None and details['model'] is None
    assert not details['use_vision']
    assert details['reviewed_sidecar_binding_counts'] == {'considered':1,'matched':1,'unmatched':0}
    report = generate_remediation_report_for_api(
        original_filename='source.pdf',file_id='fixture',report_id='fixture',file_type='pdf',
        analysis_report={'all_issues':[]},remediation_results=[result],
        remediated_file_path=str(working),output_dir=tmp_path)
    with fitz.open(report) as pdf:
        text = ' '.join(page.get_text() for page in pdf)
    assert '1 model-reviewed sidecar mapping(s)' in text
    assert 'No external Unicode verifier was invoked.' in text
    assert 'Unicode Mapping Evidence' in text
    assert 'requested but unavailable' not in text
    assert 'all Unicode decisions were deterministic' not in text
