import fitz
import pytest
import pikepdf

from backend import config, pdf_remediator_fixes as fixes, pdf_link_descriptions
from backend.remediator import PDFRemediator
from backend.pdf_tagging_gate import RequiredPDFTaggingError


@pytest.mark.parametrize("count", [3, None])
@pytest.mark.parametrize("success", [True, False])
@pytest.mark.parametrize("glyph_opt_in", [True, False])
@pytest.mark.parametrize("math_opt_in", [True, False])
def test_pipeline_retains_script_review_evidence(tmp_path, monkeypatch, count, success, glyph_opt_in, math_opt_in):
    path = tmp_path / "document.pdf"
    with fitz.open() as document:
        document.new_page().insert_text((30, 40), "Scientific text")
        document.save(path)
    glyph_sidecar = tmp_path / "review.json"
    glyph_original = tmp_path / "readonly-original.pdf"
    engine = PDFRemediator(path, reviewed_glyph_sidecar=glyph_sidecar if glyph_opt_in else None,
                          reviewed_glyph_original=glyph_original if glyph_opt_in else None,
                          reviewed_math_sidecar=glyph_sidecar if math_opt_in else None,
                          reviewed_math_original=glyph_original if math_opt_in else None)
    monkeypatch.setattr(config.settings, "DISABLE_OPENDATALOADER", False)
    monkeypatch.setattr(engine, "fix_metadata", lambda **kwargs: [])
    tag_result = {"success": success, "tags_created": 1, "pages_processed": 1,
                  "tag_counts": {"P": 1}, "error": "test failure"}
    if count is not None:
        tag_result["inline_script_review_count"] = count
        tag_result["table_review_count"] = count
    def tag_document(**kwargs):
        if success:
            with pikepdf.open(path, allow_overwriting_input=True) as pdf:
                page = pdf.pages[0]
                root = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name('/StructTreeRoot')))
                owner = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name('/StructElem'),
                    S=pikepdf.Name('/P'), P=root, Pg=page.obj, K=0))
                root.K = pikepdf.Array([owner])
                root.ParentTree = pikepdf.Dictionary(Nums=pikepdf.Array([0, pikepdf.Array([owner])]))
                pdf.Root.StructTreeRoot = root
                page.StructParents = 0
                streams = list(page.Contents) if isinstance(page.Contents, pikepdf.Array) else [page.Contents]
                content = b'\n'.join(stream.read_bytes() for stream in streams)
                page.Contents = pdf.make_stream(b'/P <</MCID 0>> BDC\n' + content + b'\nEMC')
                pdf.save(path)
        return tag_result
    monkeypatch.setattr(engine, "auto_tag_document", tag_document)
    names = ("fix_scanned_pages", "fix_pdf_unicode_mappings", "inject_link_annotations",
             "fix_content_stream_operator_states", "fix_heading_hierarchy", "fix_table_headers",
             "fix_list_structure", "fix_span_overuse", "fix_reading_order", "fix_untagged_urls",
             "fix_bookmarks", "fix_form_labels", "fix_tab_order")
    for name in names:
        monkeypatch.setattr(fixes, name, lambda path: {"issue_id": "test", "success": True, "message": "ok"})
    glyph_calls = []
    def unicode_fix(path, **kwargs):
        glyph_calls.append(kwargs)
        return {"issue_id": "test", "success": True, "message": "ok"}
    monkeypatch.setattr(fixes, "fix_pdf_unicode_mappings", unicode_fix)
    downstream_calls = []
    def downstream_fix(path):
        downstream_calls.append(path)
        return {"issue_id": "test", "success": True, "message": "ok"}
    monkeypatch.setattr(fixes, "fix_content_stream_operator_states", downstream_fix)
    monkeypatch.setattr(pdf_link_descriptions, "repair_link_descriptions",
                        lambda path: {"issue_id": "test", "success": True, "message": "ok"})
    if not success:
        with pytest.raises(RequiredPDFTaggingError, match='required PDF tagging failed: test failure'):
            engine.fix_all()
        assert downstream_calls == []
        return
    results = engine.fix_all()
    expected={"reviewed_glyph_sidecar":glyph_sidecar,"reviewed_glyph_original":glyph_original} if glyph_opt_in else {}
    if math_opt_in:expected.update(reviewed_math_sidecar=glyph_sidecar,reviewed_math_original=glyph_original)
    assert glyph_calls == [expected]
    target = next(item for item in results if item.issue_id == "pdf-validation-target")
    assert target.details == {
        "validation_target": "PDF/UA-1", "validation_profile": "ua1",
        "conformance_state": "not-verified", "conformance_identifier_written": False}
    with pikepdf.open(path) as pdf:
        with pdf.open_metadata() as metadata:
            assert "pdfuaid:part" not in metadata
    result = next(item for item in results if item.issue_id == "pdf-auto-tag")
    assert result.success is success
    # Missing evidence remains unknown, rather than silently becoming zero.
    assert result.model_dump()["details"]["inline_script_review_count"] == count
    assert result.model_dump()["details"]["table_review_count"] == count
