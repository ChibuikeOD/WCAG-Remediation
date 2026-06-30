# Ambiguous PDF Unicode Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repair used PDF character codes that lack Unicode mappings, calling DeepSeek V4 Pro only when font evidence is ambiguous and disclosing every LLM-assisted decision.

**Architecture:** A new `pdf_unicode_mapping` module owns PDF inspection, deterministic resolution, visual context collection, transactional CMap updates, and verification. A separate `deepseek_unicode_verifier` module owns the multimodal request and strict response gate. `PDFRemediator.fix_all()` invokes the repair after OCR and before structure rebuilding, while `RemediationResult.details` and the JSON remediation report expose whether DeepSeek was invoked and whether its recommendation was applied.

**Tech Stack:** Python 3.10, pikepdf 8.11.2, PyMuPDF 1.23.8, fontTools, Pillow, httpx, Pydantic 2, pytest

---

## File Structure

- Create `backend/pdf_unicode_mapping.py`: CMap parsing, CID inventory, deterministic font resolution, glyph/context rendering, transactional update, and post-write verification.
- Create `backend/deepseek_unicode_verifier.py`: DeepSeek V4 Pro prompt construction, random vision probe, strict JSON parsing, and acceptance gate.
- Create `backend/tests/test_pdf_unicode_mapping.py`: synthetic PDF and unit/integration coverage for detection, resolution, updates, rollback, and orchestration.
- Create `backend/tests/test_deepseek_unicode_verifier.py`: prompt, probe, API failure, schema, and rejection-gate coverage.
- Modify `backend/config.py`: explicit Unicode-verifier settings.
- Modify `backend/env.example`: document the DeepSeek and Unicode-verifier configuration.
- Modify `backend/requirements.txt` and `api/requirements.txt`: pin fontTools.
- Modify `backend/models.py`: add optional structured details to remediation results.
- Modify `backend/remediator.py`: add the Unicode repair stage after OCR.
- Modify `backend/pdf_remediator_fixes.py`: expose the Unicode repair through the existing fix-function interface.
- Modify `backend/remediation_report.py`: add an explicit LLM disclosure summary and retain decision details.
- Modify `backend/tests/test_pdf_remediation_contract.py`: require the new stage in the full remediation pipeline.
- Create `backend/tests/test_remediation_report_llm_disclosure.py`: verify the four disclosure states.

### Task 1: Result Contract and Configuration

**Files:**
- Modify: `backend/models.py:161-168`
- Modify: `backend/config.py:120-130`
- Modify: `backend/env.example`
- Modify: `backend/requirements.txt`
- Modify: `api/requirements.txt`
- Test: `backend/tests/test_pdf_remediation_contract.py`

- [ ] **Step 1: Write failing contract tests**

Add tests that require structured details and fixed verifier configuration:

```python
from backend.config import Settings
from backend.models import RemediationResult


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
```

- [ ] **Step 2: Run the tests and confirm RED**

Run: `python -m pytest backend/tests/test_pdf_remediation_contract.py -q`

Expected: failures for missing `details` and missing settings.

- [ ] **Step 3: Implement the contract and settings**

Add this field to `RemediationResult`:

```python
details: Optional[Dict[str, Any]] = None
```

Add these settings:

```python
PDF_UNICODE_LLM_ENABLED: bool = True
PDF_UNICODE_LLM_MODEL: str = "deepseek-v4-pro"
PDF_UNICODE_LLM_MIN_CONFIDENCE: float = Field(default=0.98, ge=0.0, le=1.0)
PDF_UNICODE_LLM_TIMEOUT_SECONDS: float = Field(default=45.0, gt=0.0)
PDF_UNICODE_LLM_MAX_OCCURRENCES: int = Field(default=3, ge=1, le=5)
```

Document the same variable names in `backend/env.example`. Add `fonttools==4.47.2` to both requirements files.

- [ ] **Step 4: Run the tests and confirm GREEN**

Run: `python -m pytest backend/tests/test_pdf_remediation_contract.py -q`

Expected: all contract tests pass.

- [ ] **Step 5: Commit**

```powershell
git add backend/models.py backend/config.py backend/env.example backend/requirements.txt api/requirements.txt backend/tests/test_pdf_remediation_contract.py
git commit -m "feat: add PDF Unicode repair configuration"
```

### Task 2: CMap Parser, CID Inventory, and Safe Writer

**Files:**
- Create: `backend/pdf_unicode_mapping.py`
- Create: `backend/tests/test_pdf_unicode_mapping.py`

- [ ] **Step 1: Write failing parser and inventory tests**

Create a synthetic PDF helper whose page uses `/F1` with `<0B36> Tj`, while its `/ToUnicode` stream maps only `<0374>` to `<0032>`. Test the public data model and inventory:

```python
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
    cmap = parse_to_unicode_cmap(SAMPLE_CMAP)
    updated = add_cmap_mappings(SAMPLE_CMAP, {0x0B36: "2"})
    reparsed = parse_to_unicode_cmap(updated)
    assert reparsed.mappings[0x0374] == "2"
    assert reparsed.mappings[0x0B36] == "2"
```

The synthetic helper builds a valid pikepdf page, Type0 font dictionary, CIDFont descendant, two-byte code space, and content stream without requiring an operating-system font.

- [ ] **Step 2: Run the focused tests and confirm RED**

Run: `python -m pytest backend/tests/test_pdf_unicode_mapping.py -k "inventory or cmap" -q`

Expected: import failure because `backend.pdf_unicode_mapping` does not exist.

- [ ] **Step 3: Implement focused data types and CMap support**

Define immutable types:

```python
@dataclass(frozen=True)
class TextOccurrence:
    page_number: int
    font_objgen: tuple[int, int]
    resource_name: str
    cid: int


@dataclass(frozen=True)
class MissingUnicodeFinding:
    font_objgen: tuple[int, int]
    base_font: str
    cid: int
    gid: Optional[int]
    occurrences: tuple[TextOccurrence, ...]

    @property
    def occurrence_count(self) -> int:
        return len(self.occurrences)

    @property
    def pages(self) -> tuple[int, ...]:
        return tuple(sorted({item.page_number for item in self.occurrences}))


@dataclass(frozen=True)
class ParsedToUnicode:
    code_width: int
    mappings: dict[int, str]
```

Implement `parse_to_unicode_cmap(data: bytes)`, supporting `begincodespacerange`, `beginbfchar`, and both scalar and array `beginbfrange` forms. Decode destinations as UTF-16BE and reject invalid surrogate sequences.

Implement `inventory_missing_unicode(pdf_path)` by recursively traversing page and Form XObject resources, parsing `Tf` plus text-showing operators with `pikepdf.parse_content_stream()`, and decoding strings according to the CMap code width or Identity-H/Identity-V two-byte encoding.

Implement `add_cmap_mappings(data, mappings)` by inserting a new `beginbfchar` block immediately before `endcmap`, limiting each block to 100 entries and refusing to overwrite an existing source code.

- [ ] **Step 4: Run the focused tests and confirm GREEN**

Run: `python -m pytest backend/tests/test_pdf_unicode_mapping.py -k "inventory or cmap" -q`

Expected: all selected tests pass.

- [ ] **Step 5: Commit**

```powershell
git add backend/pdf_unicode_mapping.py backend/tests/test_pdf_unicode_mapping.py
git commit -m "feat: detect missing PDF Unicode mappings"
```

### Task 3: Deterministic Resolver and Context Package

**Files:**
- Modify: `backend/pdf_unicode_mapping.py`
- Modify: `backend/tests/test_pdf_unicode_mapping.py`

- [ ] **Step 1: Write failing deterministic-resolution tests**

Cover a unique embedded-font mapping, conflicting evidence, and visual context:

```python
def test_unique_gid_mapping_resolves_without_llm() -> None:
    evidence = FontEvidence(unicode_by_gid={2870: ("2",)}, glyph_name_by_gid={})
    result = resolve_deterministically(finding(gid=2870), evidence)
    assert result == DeterministicResolution(text="2", evidence=("font-cmap",))


def test_conflicting_font_evidence_stays_ambiguous() -> None:
    evidence = FontEvidence(
        unicode_by_gid={2870: ("2",)},
        glyph_name_by_gid={2870: "two.superior"},
        unicode_by_glyph_name={"two.superior": "²"},
    )
    assert resolve_deterministically(finding(gid=2870), evidence) is None


def test_context_package_contains_multiple_occurrences_and_unknown_marker(monkeypatch) -> None:
    package = build_ambiguity_context(pdf_path, finding_with_three_occurrences())
    assert len(package.line_images) == 3
    assert all("[UNKNOWN]" in item.masked_line for item in package.occurrences)
    assert package.typography.position in {"superscript", "subscript", "baseline"}
```

- [ ] **Step 2: Run tests and confirm RED**

Run: `python -m pytest backend/tests/test_pdf_unicode_mapping.py -k "deterministic or context_package" -q`

Expected: missing resolver/context APIs.

- [ ] **Step 3: Implement deterministic evidence collection**

Use `fitz.Document.extract_font()` plus `fontTools.ttLib.TTFont` to build Unicode-by-GID maps, glyph-name evidence, and GSUB relationships. Parse `/CIDToGIDMap` when it is a stream; treat `/Identity` as CID equals GID. Return a resolution only when all authoritative sources converge on one Unicode sequence.

Define:

```python
@dataclass(frozen=True)
class AmbiguityContext:
    document_title: str
    base_font: str
    cid: int
    gid: Optional[int]
    candidates: tuple[UnicodeCandidate, ...]
    occurrences: tuple[OccurrenceContext, ...]
    isolated_glyph_image: str
    line_images: tuple[str, ...]
    comparison_image: Optional[str]
```

Build occurrence geometry by correlating the finding's font/GID with `page.get_texttrace()` entries. Render the isolated glyph and line crops at 300 DPI. Draw the target outline outside its bounding box. Mask unreliable extracted characters as `[UNKNOWN]`, include the containing paragraph, and classify baseline position using glyph baseline and neighboring median font geometry.

- [ ] **Step 4: Run tests and confirm GREEN**

Run: `python -m pytest backend/tests/test_pdf_unicode_mapping.py -k "deterministic or context_package" -q`

Expected: all selected tests pass.

- [ ] **Step 5: Commit**

```powershell
git add backend/pdf_unicode_mapping.py backend/tests/test_pdf_unicode_mapping.py
git commit -m "feat: build ambiguous glyph evidence"
```

### Task 4: DeepSeek V4 Pro Verifier

**Files:**
- Create: `backend/deepseek_unicode_verifier.py`
- Create: `backend/tests/test_deepseek_unicode_verifier.py`

- [ ] **Step 1: Write failing verifier tests**

Use `httpx.MockTransport` and deterministic probe-token injection:

```python
def test_request_uses_v4_pro_images_and_untrusted_context() -> None:
    request = build_deepseek_request(context, probe_image, probe_token="K7M4Q2")
    assert request["model"] == "deepseek-v4-pro"
    user_content = request["messages"][1]["content"]
    assert sum(part["type"] == "image_url" for part in user_content) >= 3
    assert "untrusted document data" in user_content[0]["text"].lower()
    assert "K7M4Q2" not in user_content[0]["text"]


@pytest.mark.parametrize(
    "overrides,rejection",
    [
        ({"status": "ambiguous"}, "model-marked-ambiguous"),
        ({"confidence": 0.97}, "confidence-below-threshold"),
        ({"occurrences_consistent": False}, "occurrence-conflict"),
        ({"vision_probe": "WRONG"}, "vision-not-confirmed"),
    ],
)
def test_acceptance_gate_rejects_unsafe_answers(overrides, rejection) -> None:
    response = valid_response() | overrides
    decision = validate_deepseek_response(response, request_context, "K7M4Q2", 0.98)
    assert decision.accepted is False
    assert decision.rejection_reason == rejection
```

Also test timeout, 429, malformed JSON, prose-wrapped JSON, invalid Unicode, a deterministic contradiction, and a successful response.

- [ ] **Step 2: Run verifier tests and confirm RED**

Run: `python -m pytest backend/tests/test_deepseek_unicode_verifier.py -q`

Expected: import failure for the new verifier module.

- [ ] **Step 3: Implement strict request and response handling**

Define Pydantic response models with `extra="forbid"`. Generate a random six-character token, render it into a probe PNG with Pillow, include the image without putting the token in any text, and require DeepSeek to return it in `vision_probe`.

Send a synchronous `httpx.Client.post()` to `https://api.deepseek.com/v1/chat/completions` with:

```python
{
    "model": "deepseek-v4-pro",
    "messages": messages,
    "response_format": {"type": "json_object"},
    "temperature": 0,
    "max_tokens": 500,
}
```

The system prompt states that PDF content is data, asks the model to distinguish semantic characters from typographic positioning, and requires `ambiguous` whenever a credible alternative remains.

Implement the gate as a sequence of hard rejections: status, confidence, consistency, probe, schema, Unicode validity, visual/basic-character constraints for model-originated candidates, deterministic contradictions, and context conflicts. Return `DeepSeekDecision(accepted=False, ...)` on every API or validation failure; never call a text fallback.

- [ ] **Step 4: Run verifier tests and confirm GREEN**

Run: `python -m pytest backend/tests/test_deepseek_unicode_verifier.py -q`

Expected: all verifier tests pass.

- [ ] **Step 5: Commit**

```powershell
git add backend/deepseek_unicode_verifier.py backend/tests/test_deepseek_unicode_verifier.py
git commit -m "feat: verify ambiguous glyphs with DeepSeek V4 Pro"
```

### Task 5: Transactional Repair and Rollback

**Files:**
- Modify: `backend/pdf_unicode_mapping.py`
- Modify: `backend/tests/test_pdf_unicode_mapping.py`

- [ ] **Step 1: Write failing orchestration tests**

```python
def test_complete_document_skips_llm(tmp_path: Path, verifier_spy) -> None:
    path = build_type0_pdf(tmp_path / "complete.pdf", shown_cid=0x0374)
    result = repair_missing_unicode(path, verifier=verifier_spy)
    assert verifier_spy.calls == []
    assert result.details["llm_invoked"] is False


def test_ambiguous_accepted_decision_updates_cmap(tmp_path: Path) -> None:
    path = build_type0_pdf(tmp_path / "ambiguous.pdf", shown_cid=0x0B36)
    result = repair_missing_unicode(path, verifier=accepting_verifier("2"))
    assert read_font_cmap(path).mappings[0x0B36] == "2"
    assert result.details["llm_invoked"] is True
    assert result.details["llm_recommendation_applied"] is True


def test_rejected_decision_does_not_change_pdf(tmp_path: Path) -> None:
    path = build_type0_pdf(tmp_path / "rejected.pdf", shown_cid=0x0B36)
    before = path.read_bytes()
    result = repair_missing_unicode(path, verifier=rejecting_verifier("occurrence-conflict"))
    assert path.read_bytes() == before
    assert result.details["llm_recommendation_applied"] is False


def test_failed_post_write_verification_rolls_back(tmp_path: Path, monkeypatch) -> None:
    path = build_type0_pdf(tmp_path / "rollback.pdf", shown_cid=0x0B36)
    before = path.read_bytes()
    monkeypatch.setattr(unicode_module, "verify_repair", lambda *_args: (False, "visual-diff"))
    result = repair_missing_unicode(path, verifier=accepting_verifier("2"))
    assert path.read_bytes() == before
    assert result.success is False
```

- [ ] **Step 2: Run tests and confirm RED**

Run: `python -m pytest backend/tests/test_pdf_unicode_mapping.py -k "skips_llm or accepted_decision or rejected_decision or rolls_back" -q`

Expected: missing orchestration API.

- [ ] **Step 3: Implement transactional orchestration**

Implement `repair_missing_unicode(pdf_path, verifier, settings)`:

1. Inventory findings.
2. Resolve deterministic findings without calling `verifier`.
3. Build ambiguity context and call `verifier` only for unresolved findings.
4. Record one decision object per font/CID.
5. Write accepted changes to a temporary sibling PDF.
6. Rescan the temporary PDF, extract affected text, compare affected-page pixmaps with Pillow `ImageChops.difference()`, and run bundled qpdf `--check` when available.
7. Replace the original atomically only after all verification passes; otherwise delete the temporary file and preserve the original.

Return the standard fix dictionary:

```python
{
    "issue_id": "pdf-unicode-mapping",
    "success": True,
    "message": disclosure,
    "new_value": "2 Unicode mapping(s) added",
    "details": {
        "llm_invoked": True,
        "llm_recommendation_applied": True,
        "model": "deepseek-v4-pro",
        "evaluated": 1,
        "applied": 1,
        "decisions": decision_records,
    },
}
```

- [ ] **Step 4: Run tests and confirm GREEN**

Run: `python -m pytest backend/tests/test_pdf_unicode_mapping.py -q`

Expected: all Unicode mapping tests pass.

- [ ] **Step 5: Commit**

```powershell
git add backend/pdf_unicode_mapping.py backend/tests/test_pdf_unicode_mapping.py
git commit -m "feat: repair PDF Unicode maps transactionally"
```

### Task 6: Pipeline and Report Integration

**Files:**
- Modify: `backend/remediator.py:592-750`
- Modify: `backend/remediation_report.py:437-505`
- Modify: `backend/tests/test_pdf_remediation_contract.py`
- Create: `backend/tests/test_remediation_report_llm_disclosure.py`

- [ ] **Step 1: Write failing pipeline/report tests**

Require `fix_pdf_unicode_mappings` immediately after OCR and explicit summary disclosure:

```python
def test_fix_all_runs_unicode_repair_after_ocr(monkeypatch, tmp_path: Path) -> None:
    calls = []
    monkeypatch.setattr(fixes, "fix_scanned_pages", recording_fix("ocr", calls))
    monkeypatch.setattr(fixes, "fix_pdf_unicode_mappings", recording_fix("unicode", calls))
    remediator.fix_all()
    assert calls.index("unicode") == calls.index("ocr") + 1


@pytest.mark.parametrize(
    "details,expected",
    [
        ({"llm_invoked": False, "llm_recommendation_applied": False}, "was not used"),
        ({"llm_invoked": True, "llm_recommendation_applied": True, "evaluated": 1, "applied": 1}, "1 recommendation(s) were applied"),
        ({"llm_invoked": True, "llm_recommendation_applied": False, "evaluated": 1, "applied": 0}, "0 recommendation(s) were applied"),
        ({"llm_invoked": False, "llm_unavailable": True}, "requested but unavailable"),
    ],
)
def test_report_contains_llm_disclosure(details, expected, tmp_path: Path) -> None:
    path = generate_report_with_unicode_details(tmp_path, details)
    report = json.loads(path.read_text(encoding="utf-8"))
    assert expected in report["summary"]["llm_disclosure"]
```

- [ ] **Step 2: Run tests and confirm RED**

Run: `python -m pytest backend/tests/test_pdf_remediation_contract.py backend/tests/test_remediation_report_llm_disclosure.py -q`

Expected: missing fix function and disclosure field.

- [ ] **Step 3: Integrate the repair stage**

Expose `fix_pdf_unicode_mappings(path)` from `pdf_remediator_fixes.py` as a thin adapter that imports `repair_missing_unicode`, creates the DeepSeek verifier only when an ambiguous finding exists, and uses `settings.DEEPSEEK_API_KEY`.

In `PDFRemediator.fix_all()`, invoke the adapter directly after `fix_scanned_pages`, pass `details=r.get("details")` into `RemediationResult`, and include the function in contract-test stubs.

In `generate_remediation_report_for_api()`, locate the `pdf-unicode-mapping` result and add `summary.llm_disclosure`. Preserve the full structured decision details under `results`.

- [ ] **Step 4: Run integration tests and confirm GREEN**

Run: `python -m pytest backend/tests/test_pdf_remediation_contract.py backend/tests/test_remediation_report_llm_disclosure.py -q`

Expected: all selected tests pass.

- [ ] **Step 5: Commit**

```powershell
git add backend/remediator.py backend/pdf_remediator_fixes.py backend/remediation_report.py backend/tests/test_pdf_remediation_contract.py backend/tests/test_remediation_report_llm_disclosure.py
git commit -m "feat: integrate Unicode repair into PDF remediation"
```

### Task 7: Regression and Real-PDF Verification

**Files:**
- Modify: `backend/tests/test_pdf_unicode_mapping.py`
- Modify: `README.md`

- [ ] **Step 1: Add an opt-in dissertation regression test**

```python
@pytest.mark.skipif(
    not Path("Check PDFs/Duseau K.L. CAS PhD Dissertation 2025.pdf").exists(),
    reason="local dissertation fixture is not available",
)
def test_dissertation_detects_ambiguous_superscript_without_hardcoding() -> None:
    pdf_path = Path("Check PDFs/Duseau K.L. CAS PhD Dissertation 2025.pdf")
    findings = inventory_missing_unicode(pdf_path)
    assert any(finding.occurrence_count > 1 for finding in findings)
    for item in findings:
        evidence = collect_font_evidence(pdf_path, item)
        assert resolve_deterministically(item, evidence) is None
```

- [ ] **Step 2: Run the focused regression before an API call**

Run: `python -m pytest backend/tests/test_pdf_unicode_mapping.py -k dissertation -q`

Expected: PASS and at least one ambiguous repeated glyph finding.

- [ ] **Step 3: Document behavior and configuration**

Add a README section explaining:

- deterministic mapping repair does not invoke DeepSeek;
- ambiguous mappings use `deepseek-v4-pro` only when `DEEPSEEK_API_KEY` is set;
- rejection leaves the PDF unchanged;
- remediation reports disclose invocation and application separately;
- the feature fails closed if multimodal input is not confirmed.

- [ ] **Step 4: Run the complete backend suite**

Run: `python -m pytest backend/tests -q`

Expected: all tests pass with no unexpected warnings.

- [ ] **Step 5: Verify both PDFs structurally and visually**

Run the remediation on a copy of `Check PDFs/Duseau K.L. CAS PhD Dissertation 2025.pdf`. With no API key, confirm the report says DeepSeek was requested but unavailable and the ambiguous CMap remains unchanged. With a configured key, confirm the model processes images, the acceptance gate result is disclosed, qpdf reports no errors, and affected pages render without pixel differences.

- [ ] **Step 6: Commit**

```powershell
git add backend/tests/test_pdf_unicode_mapping.py README.md
git commit -m "test: cover ambiguous PDF Unicode remediation"
```

### Task 8: Final Verification

**Files:** None

- [ ] **Step 1: Run formatting and diff checks**

Run: `git diff --check`

Expected: no output.

- [ ] **Step 2: Run all targeted tests again**

Run: `python -m pytest backend/tests/test_pdf_unicode_mapping.py backend/tests/test_deepseek_unicode_verifier.py backend/tests/test_pdf_remediation_contract.py backend/tests/test_remediation_report_llm_disclosure.py -q`

Expected: all tests pass.

- [ ] **Step 3: Run the full backend suite**

Run: `python -m pytest backend/tests -q`

Expected: all tests pass.

- [ ] **Step 4: Inspect repository state**

Run: `git status --short`

Expected: only intentional implementation changes, or a clean worktree after task commits.
