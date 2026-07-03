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


def test_unicode_verifier_defaults_to_gemini_flash_lite() -> None:
    settings = Settings()

    assert settings.GEMINI_MODEL == "gemini-3.1-flash-lite"
    assert settings.PDF_UNICODE_LLM_MIN_CONFIDENCE == 0.98


def test_settings_load_gemini_key_from_backend_env(tmp_path: Path, monkeypatch) -> None:
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir()
    (backend_dir / ".env").write_text(
        "GEMINI_API_KEY=backend-env-key\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)

    settings = Settings()

    assert settings.GEMINI_API_KEY == "backend-env-key"


def test_unicode_repair_uses_configured_gemini_vision_verifier(
    tmp_path: Path, monkeypatch
) -> None:
    from backend import config
    from backend import gemini_unicode_verifier
    from backend import pdf_remediator_fixes as fixes
    from backend import pdf_unicode_mapping
    from backend.deepseek_unicode_verifier import DeepSeekDecision

    captured = {}

    def fake_verify(context, **kwargs):
        captured.update(kwargs)
        captured["images"] = context["images"]
        return DeepSeekDecision(True, "2", 0.99, None)

    def fake_repair(
        path, *, verifier, max_occurrences, provider_name, provider_label, model_name
    ):
        assert provider_name == "Gemini"
        assert provider_label == "Gemini 3.1 Flash-Lite"
        assert model_name == "gemini-3.1-flash-lite"
        decision = verifier({"images": ["data:image/png;base64,AAAA"]})
        assert decision.accepted is True
        return {
            "issue_id": "pdf-unicode-mapping",
            "success": True,
            "details": {},
        }

    monkeypatch.setattr(config.settings, "PDF_UNICODE_LLM_ENABLED", True)
    monkeypatch.setattr(config.settings, "GEMINI_API_KEY", "gemini-secret")
    monkeypatch.setattr(
        config.settings, "GEMINI_MODEL", "gemini-3.1-flash-lite"
    )
    monkeypatch.setattr(
        config.settings,
        "GEMINI_API_ENDPOINT",
        "https://example.test/chat/completions",
    )
    monkeypatch.setattr(gemini_unicode_verifier, "verify_ambiguous_unicode", fake_verify)
    monkeypatch.setattr(pdf_unicode_mapping, "repair_missing_unicode", fake_repair)

    result = fixes.fix_pdf_unicode_mappings(tmp_path / "document.pdf")

    assert result["success"] is True
    assert captured["api_key"] == "gemini-secret"
    assert captured["model"] == "gemini-3.1-flash-lite"
    assert captured["endpoint"] == "https://example.test/chat/completions"
    assert captured["images"]


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
