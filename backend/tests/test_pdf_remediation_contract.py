import inspect
from pathlib import Path

import pikepdf

from backend.config import Settings
from backend.models import RemediationRequest, RemediationResult
from backend.remediator import PDFRemediator


def _make_minimal_pdf(path: Path) -> None:
    with pikepdf.Pdf.new() as pdf:
        pdf.add_blank_page(page_size=(72, 72))
        pdf.save(path)


def test_remediation_request_does_not_expose_structure_rebuild_opt_out() -> None:
    request = RemediationRequest.model_validate(
        {
            "report_id": "report-1",
            "apply_all_automatable": True,
            "overwrite_tags": False,
        }
    )

    assert "overwrite_tags" not in request.model_dump()


def test_full_pdf_remediation_has_no_structure_rebuild_opt_out() -> None:
    assert "overwrite_tags" not in inspect.signature(PDFRemediator.fix_all).parameters


def test_remediation_result_accepts_unicode_decision_details() -> None:
    result = RemediationResult(
        issue_id="pdf-unicode-mapping",
        success=True,
        message="DeepSeek V4 Pro was not used",
        details={"llm_invoked": False, "llm_recommendation_applied": False},
    )

    assert result.details == {
        "llm_invoked": False,
        "llm_recommendation_applied": False,
    }


def test_unicode_verifier_model_is_deepseek_v4_pro() -> None:
    settings = Settings()

    assert settings.PDF_UNICODE_LLM_MODEL == "deepseek-v4-pro"
    assert settings.PDF_UNICODE_LLM_MIN_CONFIDENCE == 0.98


def test_full_pdf_remediation_always_requests_structure_overwrite(
    tmp_path: Path, monkeypatch
) -> None:
    from backend import config
    from backend import pdf_remediator_fixes as fixes

    pdf_path = tmp_path / "minimal.pdf"
    _make_minimal_pdf(pdf_path)
    remediator = PDFRemediator(pdf_path)
    captured: dict[str, object] = {}

    monkeypatch.setattr(config.settings, "DISABLE_OPENDATALOADER", False)
    monkeypatch.setattr(remediator, "fix_metadata", lambda **_kwargs: [])

    def fake_auto_tag_document(**kwargs):
        captured.update(kwargs)
        return {
            "success": True,
            "tags_created": 1,
            "pages_processed": 1,
            "tag_counts": {"P": 1},
        }

    monkeypatch.setattr(remediator, "auto_tag_document", fake_auto_tag_document)

    fix_names = (
        "fix_scanned_pages",
        "fix_pdf_unicode_mappings",
        "inject_link_annotations",
        "fix_content_stream_operator_states",
        "fix_heading_hierarchy",
        "fix_table_headers",
        "fix_list_structure",
        "fix_span_overuse",
        "fix_reading_order",
        "fix_untagged_urls",
        "fix_bookmarks",
        "fix_form_labels",
        "fix_tab_order",
    )
    for fix_name in fix_names:
        monkeypatch.setattr(
            fixes,
            fix_name,
            lambda _path: {
                "issue_id": "test-fix",
                "success": True,
                "message": "ok",
            },
        )

    results = remediator.fix_all()

    assert captured["overwrite_tags"] is True
    assert any(
        result.issue_id == "pdf-auto-tag" and result.success for result in results
    )


def test_fix_all_runs_unicode_repair_immediately_after_ocr(
    tmp_path: Path, monkeypatch
) -> None:
    from backend import config
    from backend import pdf_remediator_fixes as fixes

    pdf_path = tmp_path / "minimal.pdf"
    _make_minimal_pdf(pdf_path)
    remediator = PDFRemediator(pdf_path)
    calls: list[str] = []

    monkeypatch.setattr(config.settings, "DISABLE_OPENDATALOADER", True)
    monkeypatch.setattr(remediator, "fix_metadata", lambda **_kwargs: [])

    def recording_fix(name: str):
        def run(_path: Path):
            calls.append(name)
            return {"issue_id": f"test-{name}", "success": True, "message": "ok"}

        return run

    monkeypatch.setattr(fixes, "fix_scanned_pages", recording_fix("ocr"))
    monkeypatch.setattr(
        fixes, "fix_pdf_unicode_mappings", recording_fix("unicode")
    )
    for fix_name in (
        "inject_link_annotations",
        "fix_content_stream_operator_states",
        "fix_heading_hierarchy",
        "fix_table_headers",
        "fix_list_structure",
        "fix_span_overuse",
        "fix_reading_order",
        "fix_untagged_urls",
        "fix_bookmarks",
        "fix_form_labels",
        "fix_tab_order",
    ):
        monkeypatch.setattr(fixes, fix_name, recording_fix(fix_name))

    remediator.fix_all()

    assert calls[:2] == ["ocr", "unicode"]
