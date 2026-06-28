# Always Rebuild PDF Structure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the request-level PDF structure rebuild option and make the full PDF remediation pipeline rebuild structure on every run unless the deployment kill switch is active.

**Architecture:** The public remediation request will no longer carry `overwrite_tags`, and the frontend will no longer render or submit that choice. The full `PDFRemediator.fix_all` orchestration method will own the invariant by always calling its lower-level auto-tagging method with `overwrite_tags=True`; the low-level argument remains because it describes how the tagging engine writes the structure tree.

**Tech Stack:** Python 3, FastAPI, Pydantic, pytest, React 18, TypeScript, Vite

---

## File Structure

- Modify `backend/models.py`: remove the caller-controlled field from `RemediationRequest`.
- Modify `backend/main.py`: stop forwarding a structure rebuild preference into the PDF pipeline.
- Modify `backend/remediator.py`: remove the full-pipeline opt-out and always run auto-tagging when the deployment kill switch is off.
- Create `backend/tests/test_pdf_remediation_contract.py`: cover the backend request and orchestration invariants.
- Modify `frontend/src/components/RemediationPanel.tsx`: remove checkbox state, rendering, and request branching.
- Modify `frontend/src/api.ts`: remove the obsolete request property from the TypeScript API contract.
- Create `backend/tests/test_frontend_remediation_contract.py`: guard removal of the checkbox and frontend request option without introducing a second frontend test framework.

### Task 1: Lock the Backend Contract with Failing Tests

**Files:**
- Create: `backend/tests/test_pdf_remediation_contract.py`
- Test: `backend/tests/test_pdf_remediation_contract.py`

- [ ] **Step 1: Write the failing contract tests**

```python
from __future__ import annotations

import inspect
from pathlib import Path

import pikepdf

from backend.models import RemediationRequest
from backend.remediator import PDFRemediator


def _make_minimal_pdf(path: Path) -> None:
    with pikepdf.Pdf.new() as pdf:
        pdf.add_blank_page(page_size=(72, 72))
        pdf.save(path)


def test_remediation_request_does_not_expose_structure_rebuild_opt_out():
    request = RemediationRequest.model_validate(
        {
            "report_id": "report-1",
            "apply_all_automatable": True,
            "overwrite_tags": False,
        }
    )

    assert "overwrite_tags" not in request.model_dump()


def test_full_pdf_remediation_has_no_structure_rebuild_opt_out():
    assert "overwrite_tags" not in inspect.signature(PDFRemediator.fix_all).parameters


def test_full_pdf_remediation_always_requests_structure_overwrite(monkeypatch, tmp_path):
    from backend import pdf_remediator_fixes as fixes
    from backend.config import settings

    pdf_path = tmp_path / "sample.pdf"
    _make_minimal_pdf(pdf_path)
    remediator = PDFRemediator(pdf_path)
    captured: dict[str, object] = {}

    monkeypatch.setattr(settings, "DISABLE_OPENDATALOADER", False)
    monkeypatch.setattr(remediator, "fix_metadata", lambda **kwargs: [])

    def fake_auto_tag_document(**kwargs):
        captured.update(kwargs)
        return {
            "success": True,
            "tags_created": 1,
            "pages_processed": 1,
            "tag_counts": {"P": 1},
        }

    monkeypatch.setattr(remediator, "auto_tag_document", fake_auto_tag_document)

    def successful_fix(_path):
        return {"issue_id": "test-fix", "success": True, "message": "ok"}

    for name in (
        "fix_scanned_pages",
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
        monkeypatch.setattr(fixes, name, successful_fix)

    results = remediator.fix_all(output_path=pdf_path, original_filename="sample.pdf")

    assert captured["overwrite_tags"] is True
    assert any(result.issue_id == "pdf-auto-tag" and result.success for result in results)
```

- [ ] **Step 2: Run the focused tests and verify the contract tests fail**

Run: `python -m pytest backend/tests/test_pdf_remediation_contract.py -v`

Expected: the request-model test fails because `overwrite_tags` is still serialized, and the signature test fails because `fix_all` still exposes `overwrite_tags`. The orchestration test may already pass because the current default is `True`.

- [ ] **Step 3: Commit the failing tests**

```bash
git add backend/tests/test_pdf_remediation_contract.py
git commit -m "test: require unconditional PDF structure rebuild"
```

### Task 2: Enforce Structure Rebuilding in the Backend

**Files:**
- Modify: `backend/models.py:154-160`
- Modify: `backend/main.py:691-701`
- Modify: `backend/remediator.py:592-710`
- Test: `backend/tests/test_pdf_remediation_contract.py`

- [ ] **Step 1: Remove the request field from the Pydantic model**

Change `RemediationRequest` to:

```python
class RemediationRequest(BaseModel):
    """Request to apply automated remediations."""
    report_id: str
    issue_ids: Optional[List[str]] = None  # None means apply all automatable
    apply_all_automatable: bool = False
```

- [ ] **Step 2: Stop forwarding the removed request option**

Change the PDF call in `backend/main.py` to:

```python
        results = await run_in_threadpool(
            remediator.fix_all,
            output_path=output_path,
            report=report,
            original_filename=file_info["original_filename"],
        )
```

Preserve all unrelated existing changes in `backend/main.py`.

- [ ] **Step 3: Remove the full-pipeline opt-out**

Change the `fix_all` signature and opening docstring to:

```python
    def fix_all(
        self,
        output_path: Optional[Path] = None,
        report: Optional[Any] = None,
        original_filename: str = "",
    ) -> List[RemediationResult]:
        """
        Run the full PDF remediation pipeline: metadata, auto-tag, structural
        fixes, bookmarks, OCR, and form labels. Returns a flat list of
        RemediationResult for every fix attempted.
        """
```

Replace the tagging conditional with:

```python
        if not settings.DISABLE_OPENDATALOADER:
            reason = "rebuilding existing structure" if is_tagged else "untagged document"
            logger.info("Running PDF layout tagging using OpenDataLoader (%s)...", reason)
            tag_result = self.auto_tag_document(
                output_path=target,
                overwrite_tags=True,
                confidence_threshold=0.0,
            )
            if tag_result.get("success"):
                results.append(RemediationResult(
                    issue_id="pdf-auto-tag",
                    success=True,
                    message=(
                        f"Document tagging: created {tag_result['tags_created']} "
                        f"structure tags across {tag_result['pages_processed']} pages"
                    ),
                    new_value=str(tag_result.get("tag_counts", {})),
                ))
            else:
                results.append(RemediationResult(
                    issue_id="pdf-auto-tag",
                    success=False,
                    message=f"Auto-tagging failed: {tag_result.get('error', 'Unknown')}",
                ))
        else:
            logger.info("PDF layout tagging skipped (DISABLE_OPENDATALOADER is enabled)")
            results.append(RemediationResult(
                issue_id="pdf-auto-tag",
                success=False,
                message="PDF auto-tagging skipped (OpenDataLoader layout analysis disabled)",
            ))
```

- [ ] **Step 4: Run the focused backend tests and verify they pass**

Run: `python -m pytest backend/tests/test_pdf_remediation_contract.py -v`

Expected: `3 passed`.

- [ ] **Step 5: Run related backend regression tests**

Run: `python -m pytest backend/tests/test_api.py backend/tests/test_pdf_auto_tagging.py -v`

Expected: all selected tests pass.

- [ ] **Step 6: Commit the backend implementation**

```bash
git add backend/models.py backend/main.py backend/remediator.py
git commit -m "fix: always rebuild remediated PDF structure"
```

### Task 3: Lock the Frontend Removal with a Failing Test

**Files:**
- Create: `backend/tests/test_frontend_remediation_contract.py`
- Test: `backend/tests/test_frontend_remediation_contract.py`

- [ ] **Step 1: Write the failing source-contract test**

```python
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_frontend_does_not_offer_structure_rebuild_opt_out():
    panel_source = (
        REPO_ROOT / "frontend" / "src" / "components" / "RemediationPanel.tsx"
    ).read_text(encoding="utf-8")
    api_source = (REPO_ROOT / "frontend" / "src" / "api.ts").read_text(encoding="utf-8")

    assert "Rebuild structure with OpenDataLoader" not in panel_source
    assert "overwriteTags" not in panel_source
    assert "overwrite_tags?: boolean" not in api_source
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run: `python -m pytest backend/tests/test_frontend_remediation_contract.py -v`

Expected: FAIL because the checkbox label, state, and API property still exist.

- [ ] **Step 3: Commit the failing test**

```bash
git add backend/tests/test_frontend_remediation_contract.py
git commit -m "test: prohibit PDF rebuild opt-out in frontend"
```

### Task 4: Remove the Frontend Checkbox and Request Option

**Files:**
- Modify: `frontend/src/components/RemediationPanel.tsx:1-330`
- Modify: `frontend/src/api.ts:79-91`
- Test: `backend/tests/test_frontend_remediation_contract.py`

- [ ] **Step 1: Remove state and request branching**

Delete:

```tsx
  const [overwriteTags, setOverwriteTags] = useState(false);
```

Change the remediation request to:

```tsx
      const response = await remediateDocument({
        report_id: report.id,
        apply_all_automatable: true,
      });
```

- [ ] **Step 2: Remove the checkbox rendering and unused helper**

Delete the entire PDF-specific options block beginning with:

```tsx
              {/* PDF-specific options */}
```

and ending after its `{isPdf && (...)}` expression. Delete the complete `OptionRow` function. Remove the now-unused line:

```tsx
  const isPdf = report.document.file_type === 'pdf';
```

Keep the `Wrench` import because the panel header and submit button still use it.

- [ ] **Step 3: Remove the TypeScript request property**

Change the parameter type in `frontend/src/api.ts` to:

```typescript
export async function remediateDocument(params: {
  report_id: string;
  issue_ids?: string[];
  apply_all_automatable?: boolean;
}): Promise<RemediationResponse> {
```

- [ ] **Step 4: Run the frontend contract test and verify it passes**

Run: `python -m pytest backend/tests/test_frontend_remediation_contract.py -v`

Expected: `1 passed`.

- [ ] **Step 5: Run the TypeScript production build**

Run: `npm run build`

Working directory: `frontend`

Expected: TypeScript compilation and Vite build complete successfully with exit code 0.

- [ ] **Step 6: Commit the frontend implementation**

```bash
git add frontend/src/components/RemediationPanel.tsx frontend/src/api.ts
git commit -m "fix: remove PDF structure rebuild checkbox"
```

### Task 5: Final Verification

**Files:**
- Verify: `backend/tests/test_pdf_remediation_contract.py`
- Verify: `backend/tests/test_frontend_remediation_contract.py`
- Verify: all modified production files

- [ ] **Step 1: Run all focused contract tests together**

Run: `python -m pytest backend/tests/test_pdf_remediation_contract.py backend/tests/test_frontend_remediation_contract.py -v`

Expected: `4 passed`.

- [ ] **Step 2: Run the complete backend test suite**

Run: `python -m pytest backend/tests -v`

Expected: all tests pass. If environment-dependent C++ or Java integration tests are skipped, record the skip reasons; no test may fail.

- [ ] **Step 3: Re-run the frontend production build**

Run: `npm run build`

Working directory: `frontend`

Expected: exit code 0 with no TypeScript errors.

- [ ] **Step 4: Check the final diff for obsolete opt-outs and whitespace errors**

Run: `rg -n "overwriteTags|overwrite_tags|Rebuild structure with OpenDataLoader|opted out via overwrite_tags" frontend/src backend --glob '!backend/tests/test_frontend_remediation_contract.py' --glob '!backend/tests/test_pdf_remediation_contract.py'`

Expected: only the intentional low-level `auto_tag_document`/`auto_tag_pdf` overwrite controls remain; no request model, endpoint forwarding, `fix_all` parameter, checkbox, or opt-out message remains.

Run: `git diff --check`

Expected: no output and exit code 0.

- [ ] **Step 5: Commit any verification-only corrections**

If verification required corrections, stage only those files and commit them:

```bash
git add backend/models.py backend/main.py backend/remediator.py backend/tests/test_pdf_remediation_contract.py backend/tests/test_frontend_remediation_contract.py frontend/src/components/RemediationPanel.tsx frontend/src/api.ts
git commit -m "test: complete mandatory structure rebuild verification"
```

If no corrections were needed, do not create an empty commit.
