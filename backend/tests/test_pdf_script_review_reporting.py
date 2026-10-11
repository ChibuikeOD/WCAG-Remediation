import fitz
import pytest

from backend import config, pdf_remediator_fixes as fixes, pdf_link_descriptions
from backend.remediator import PDFRemediator


@pytest.mark.parametrize("count", [3, None])
@pytest.mark.parametrize("success", [True, False])
def test_pipeline_retains_script_review_evidence(tmp_path, monkeypatch, count, success):
    path = tmp_path / "document.pdf"
    with fitz.open() as document:
        document.new_page().insert_text((30, 40), "Scientific text")
        document.save(path)
    engine = PDFRemediator(path)
    monkeypatch.setattr(config.settings, "DISABLE_OPENDATALOADER", False)
    monkeypatch.setattr(engine, "fix_metadata", lambda **kwargs: [])
    tag_result = {"success": success, "tags_created": 1, "pages_processed": 1,
                  "tag_counts": {"P": 1}, "error": "test failure"}
    if count is not None:
        tag_result["inline_script_review_count"] = count
    monkeypatch.setattr(engine, "auto_tag_document", lambda **kwargs: tag_result)
    names = ("fix_scanned_pages", "fix_pdf_unicode_mappings", "inject_link_annotations",
             "fix_content_stream_operator_states", "fix_heading_hierarchy", "fix_table_headers",
             "fix_list_structure", "fix_span_overuse", "fix_reading_order", "fix_untagged_urls",
             "fix_bookmarks", "fix_form_labels", "fix_tab_order")
    for name in names:
        monkeypatch.setattr(fixes, name, lambda path: {"issue_id": "test", "success": True, "message": "ok"})
    monkeypatch.setattr(pdf_link_descriptions, "repair_link_descriptions",
                        lambda path: {"issue_id": "test", "success": True, "message": "ok"})
    result = next(item for item in engine.fix_all() if item.issue_id == "pdf-auto-tag")
    assert result.success is success
    # Missing evidence remains unknown, rather than silently becoming zero.
    assert result.model_dump()["details"]["inline_script_review_count"] == count
