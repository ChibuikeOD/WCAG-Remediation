# Downloadable Remediation Report PDF Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate a human-readable remediation PDF and let the authenticated user download it from the remediation-complete modal.

**Architecture:** The existing remediation request will render its analysis and result data directly into a ReportLab PDF whose filename includes the report ID. A new authenticated, report-ID-based endpoint will find and serve that artifact, while a small frontend URL helper powers a second download link in the existing modal footer.

**Tech Stack:** Python 3, FastAPI, ReportLab, pdfplumber, pytest, React 18, TypeScript, Vite, Tailwind CSS

---

## File Structure

- Modify `backend/remediation_report.py`: render the main remediation artifact as a human-readable PDF and preserve AI-use disclosure logic.
- Modify `backend/requirements.txt`: make ReportLab available in the Docker/backend runtime.
- Modify `api/requirements.txt`: make ReportLab available in the Vercel API runtime.
- Modify `backend/tests/test_remediation_report_llm_disclosure.py`: assert PDF validity, readable report content, and all disclosure variants.
- Modify `backend/main.py`: add the authenticated report-ID download endpoint and artifact resolver.
- Modify `backend/tests/test_api.py`: test successful, missing, and unauthorized report downloads.
- Modify `frontend/src/api.ts`: expose the report download URL helper.
- Modify `frontend/src/components/RemediationPanel.tsx`: add the post-remediation download action and responsive footer wrapping.
- Modify `backend/tests/test_frontend_remediation_contract.py`: enforce the frontend download contract.

### Task 1: Render the API Remediation Report as PDF

**Files:**
- Modify: `backend/requirements.txt`
- Modify: `api/requirements.txt`
- Modify: `backend/remediation_report.py`
- Modify: `backend/tests/test_remediation_report_llm_disclosure.py`

- [ ] **Step 1: Add failing PDF-content tests**

Replace JSON parsing in `backend/tests/test_remediation_report_llm_disclosure.py` with `pdfplumber` extraction, and add a representative content test:

```python
import pdfplumber


def extract_pdf_text(path: Path) -> str:
    with pdfplumber.open(path) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


def test_api_report_is_a_human_readable_pdf(tmp_path: Path) -> None:
    path = generate_remediation_report_for_api(
        original_filename="source.pdf",
        file_id="file-1",
        report_id="report-1",
        file_type="pdf",
        analysis_report={
            "all_issues": [
                {
                    "id": "manual-1",
                    "rule_id": "1.1.1",
                    "rule_name": "Non-text Content",
                    "severity": "error",
                    "message": "Image needs meaningful alternative text",
                    "fix_suggestion": "Write concise alternative text",
                    "automatable_fix": False,
                }
            ]
        },
        remediation_results=[
            {
                "issue_id": "pdf-title",
                "success": True,
                "message": "Document title added",
                "original_value": None,
                "new_value": "Accessible report",
            },
            {
                "issue_id": "pdf-bookmarks",
                "success": False,
                "message": "Bookmarks could not be generated",
            },
        ],
        remediated_file_path="output.pdf",
        output_dir=tmp_path,
    )

    assert path.suffix == ".pdf"
    assert path.read_bytes().startswith(b"%PDF-")
    text = extract_pdf_text(path)
    assert "PDF Accessibility Remediation Report" in text
    assert "source.pdf" in text
    assert "Successful Fixes" in text
    assert "Document title added" in text
    assert "Failed Fixes" in text
    assert "Bookmarks could not be generated" in text
    assert "Remaining Manual Work" in text
    assert "Write concise alternative text" in text
```

Update the parameterized disclosure assertion to:

```python
text = extract_pdf_text(path)
assert expected in text
```

- [ ] **Step 2: Run the report tests and verify RED**

Run:

```powershell
.\VirtualEnvironment\Scripts\python.exe -m pytest backend/tests/test_remediation_report_llm_disclosure.py -v
```

Expected: FAIL because the function currently returns `.json`, the file does not begin with `%PDF-`, and `pdfplumber` cannot open it as a PDF.

- [ ] **Step 3: Add ReportLab to both deployment requirement sets**

Add this line under each PDF-processing section in `backend/requirements.txt` and `api/requirements.txt`:

```text
reportlab==4.2.5
```

Install it into the local project environment for test execution:

```powershell
.\VirtualEnvironment\Scripts\python.exe -m pip install reportlab==4.2.5
```

- [ ] **Step 4: Implement the minimal PDF renderer**

In `backend/remediation_report.py`, import XML escaping and replace `generate_remediation_report_for_api`'s JSON write with a ReportLab story. Retain the existing `llm_disclosure` decision tree and manual-issue normalization, then render the normalized values:

```python
from xml.sax.saxutils import escape


def _safe_text(value: Any) -> str:
    return escape(str(value if value is not None else "Not provided"))


def generate_remediation_report_for_api(
    *,
    original_filename: str,
    file_id: str,
    report_id: str,
    file_type: str,
    analysis_report: Dict[str, Any],
    remediation_results: List[Dict[str, Any]],
    remediated_file_path: Optional[str],
    output_dir: Path,
) -> Path:
    if not HAS_REPORTLAB:
        raise RuntimeError("ReportLab is required to generate remediation PDF reports")

    output_dir.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now()
    timestamp = generated_at.strftime("%Y%m%d_%H%M%S")
    output_path = output_dir / f"Remediation_Report_{report_id}_{timestamp}.pdf"

    fixed = [result for result in remediation_results if result.get("success")]
    failed = [result for result in remediation_results if not result.get("success")]
    unicode_result = next(
        (
            result
            for result in remediation_results
            if result.get("issue_id") == "pdf-unicode-mapping"
        ),
        None,
    )
    unicode_details = (unicode_result or {}).get("details") or {}
    if unicode_details.get("llm_unavailable"):
        llm_disclosure = (
            "DeepSeek V4 Pro was requested but unavailable; "
            "no ambiguous mappings were changed."
        )
    elif unicode_details.get("llm_invoked"):
        evaluated = int(unicode_details.get("evaluated", 0))
        applied = int(unicode_details.get("applied", 0))
        llm_disclosure = (
            f"DeepSeek V4 Pro evaluated {evaluated} ambiguous Unicode mapping(s); "
            f"{applied} recommendation(s) were applied."
        )
    else:
        llm_disclosure = (
            "DeepSeek V4 Pro was not used; all Unicode decisions were deterministic."
        )

    manual_remaining = [
        {
            "id": issue.get("id"),
            "rule_id": issue.get("rule_id"),
            "rule_name": issue.get("rule_name"),
            "severity": issue.get("severity"),
            "message": issue.get("message"),
            "fix_suggestion": issue.get("fix_suggestion"),
        }
        for issue in analysis_report.get("all_issues", [])
        if not issue.get("automatable_fix", False)
    ]

    styles = getSampleStyleSheet()
    title = ParagraphStyle(
        "ApiReportTitle", parent=styles["Title"], textColor=HexColor("#0891b2")
    )
    heading = ParagraphStyle(
        "ApiReportHeading", parent=styles["Heading2"], textColor=HexColor("#1e3a5f")
    )
    body = styles["BodyText"]
    story = [
        Paragraph("PDF Accessibility Remediation Report", title),
        Spacer(1, 12),
        Paragraph("Document Information", heading),
        Table(
            [
                ["Original file", Paragraph(_safe_text(original_filename), body)],
                ["Report ID", Paragraph(_safe_text(report_id), body)],
                ["Generated", generated_at.strftime("%Y-%m-%d %H:%M:%S")],
            ],
            colWidths=[1.5 * inch, 5 * inch],
            style=TableStyle(
                [
                    ("BACKGROUND", (0, 0), (0, -1), HexColor("#f3f4f6")),
                    ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                    ("GRID", (0, 0), (-1, -1), 0.5, HexColor("#d1d5db")),
                    ("PADDING", (0, 0), (-1, -1), 7),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            ),
        ),
        Spacer(1, 12),
        Paragraph("Remediation Summary", heading),
        Table(
            [
                ["Issues before", "Successful fixes", "Failed fixes", "Manual remaining"],
                [
                    str(len(analysis_report.get("all_issues", []))),
                    str(len(fixed)),
                    str(len(failed)),
                    str(len(manual_remaining)),
                ],
            ],
            style=TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), HexColor("#0891b2")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                    ("GRID", (0, 0), (-1, -1), 0.5, HexColor("#d1d5db")),
                    ("PADDING", (0, 0), (-1, -1), 7),
                ]
            ),
        ),
        Spacer(1, 8),
        Paragraph(f"<b>AI-use disclosure:</b> {_safe_text(llm_disclosure)}", body),
    ]

    def append_results(title_text: str, items: List[Dict[str, Any]]) -> None:
        if not items:
            return
        story.extend([Spacer(1, 12), Paragraph(title_text, heading)])
        for item in items:
            details = [
                ["Issue", Paragraph(_safe_text(item.get("issue_id")), body)],
                ["Result", Paragraph(_safe_text(item.get("message")), body)],
            ]
            if item.get("original_value") is not None:
                details.append(["Previous value", Paragraph(_safe_text(item["original_value"]), body)])
            if item.get("new_value") is not None:
                details.append(["New value", Paragraph(_safe_text(item["new_value"]), body)])
            result_table = Table(details, colWidths=[1.3 * inch, 5.2 * inch])
            result_table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (0, -1), HexColor("#f3f4f6")),
                        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                        ("GRID", (0, 0), (-1, -1), 0.5, HexColor("#d1d5db")),
                        ("PADDING", (0, 0), (-1, -1), 6),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ]
                )
            )
            story.extend([result_table, Spacer(1, 8)])

    append_results("Successful Fixes", fixed)
    append_results("Failed Fixes", failed)

    if manual_remaining:
        story.extend([Spacer(1, 12), Paragraph("Remaining Manual Work", heading)])
        for issue in manual_remaining:
            story.extend(
                [
                    Paragraph(
                        f"<b>[{_safe_text(issue.get('rule_id'))}] "
                        f"{_safe_text(issue.get('rule_name'))}</b>",
                        body,
                    ),
                    Paragraph(_safe_text(issue.get("message")), body),
                    Paragraph(
                        f"<b>Suggested fix:</b> {_safe_text(issue.get('fix_suggestion'))}",
                        body,
                    ),
                    Spacer(1, 8),
                ]
            )

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=letter,
        rightMargin=0.75 * inch,
        leftMargin=0.75 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
        title="PDF Accessibility Remediation Report",
    )
    doc.build(story)
    logger.info("Generated remediation report: %s", output_path)
    return output_path
```

Do not add a JSON fallback: a successful call must return the promised PDF artifact.

- [ ] **Step 5: Run the report tests and verify GREEN**

Run:

```powershell
.\VirtualEnvironment\Scripts\python.exe -m pytest backend/tests/test_remediation_report_llm_disclosure.py -v
```

Expected: all report-content and disclosure cases PASS.

- [ ] **Step 6: Commit the PDF generator**

```powershell
git add backend/remediation_report.py backend/requirements.txt api/requirements.txt backend/tests/test_remediation_report_llm_disclosure.py
git commit -m "feat: generate remediation reports as PDF"
```

### Task 2: Serve the Report Through an Authenticated Endpoint

**Files:**
- Modify: `backend/main.py`
- Modify: `backend/tests/test_api.py`

- [ ] **Step 1: Add failing endpoint tests**

Add helpers and three tests to `backend/tests/test_api.py`:

```python
from backend.database import AccessibilityReport as DbReport, UploadedFile, User


def seed_owned_report(client, report_id: str, owner_id: str = "dev_user_001") -> None:
    db = main_module.SessionLocal()
    try:
        user = db.query(User).filter(User.id == owner_id).first()
        if user is None:
            user = User(id=owner_id, email=f"{owner_id}@example.com", name=owner_id)
            db.add(user)
        uploaded = UploadedFile(
            id=f"file-{report_id}",
            filename="source.pdf",
            file_type="pdf",
            file_path=str(settings.UPLOAD_DIR / "source.pdf"),
            file_size=4,
            owner_id=owner_id,
        )
        db.add(uploaded)
        db.add(DbReport(id=report_id, file_id=uploaded.id, report_json="{}"))
        db.commit()
    finally:
        db.close()


def test_download_remediation_report_serves_pdf(client):
    seed_owned_report(client, "report-download")
    report_path = settings.OUTPUT_DIR / "Remediation_Report_report-download_20260701_120000.pdf"
    report_path.write_bytes(b"%PDF-1.4\n%%EOF")

    response = client.get("/remediate/report/report-download")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert "attachment" in response.headers["content-disposition"]
    assert "Remediation_Report_report-download_20260701_120000.pdf" in response.headers["content-disposition"]


def test_download_remediation_report_returns_404_without_artifact(client):
    seed_owned_report(client, "report-missing")

    response = client.get("/remediate/report/report-missing")

    assert response.status_code == 404


def test_download_remediation_report_rejects_another_users_report(client):
    seed_owned_report(client, "report-private", owner_id="another-user")
    (settings.OUTPUT_DIR / "Remediation_Report_report-private_20260701_120000.pdf").write_bytes(
        b"%PDF-1.4\n%%EOF"
    )

    response = client.get("/remediate/report/report-private")

    assert response.status_code == 403
```

- [ ] **Step 2: Run the endpoint tests and verify RED**

Run:

```powershell
.\VirtualEnvironment\Scripts\python.exe -m pytest backend/tests/test_api.py -k "download_remediation_report" -v
```

Expected: FAIL with 404 because `/remediate/report/{report_id}` does not exist.

- [ ] **Step 3: Implement report lookup and authenticated download**

Add a focused resolver and endpoint beside `download_remediated_file` in `backend/main.py`:

```python
def _latest_remediation_report_path(report_id: str) -> Optional[Path]:
    candidates = list(
        settings.OUTPUT_DIR.glob(f"Remediation_Report_{report_id}_*.pdf")
    )
    return max(candidates, key=lambda path: path.stat().st_mtime, default=None)


@app.get("/remediate/report/{report_id}")
async def download_remediation_report_for_remediation(
    report_id: str,
    user: User = Depends(require_user),
):
    db_conn = SessionLocal()
    try:
        report_rec = db_conn.query(DbReport).filter(DbReport.id == report_id).first()
        if report_rec is None:
            raise HTTPException(status_code=404, detail="Report not found")
        file_rec = db_conn.query(UploadedFile).filter(UploadedFile.id == report_rec.file_id).first()
        if file_rec and file_rec.owner_id and file_rec.owner_id != user.id:
            raise HTTPException(status_code=403, detail="Access denied to this report.")
    finally:
        db_conn.close()

    report_path = _latest_remediation_report_path(report_id)
    if report_path is None:
        raise HTTPException(status_code=404, detail="Remediation report not found")

    return FileResponse(
        path=report_path,
        filename=report_path.name,
        media_type="application/pdf",
    )
```

Use the already imported database `User`, `DbReport`, `UploadedFile`, `Path`, `Optional`, `Depends`, `HTTPException`, and `FileResponse` symbols.

- [ ] **Step 4: Run endpoint tests and verify GREEN**

Run:

```powershell
.\VirtualEnvironment\Scripts\python.exe -m pytest backend/tests/test_api.py -k "download_remediation_report" -v
```

Expected: all three report-download endpoint tests PASS.

- [ ] **Step 5: Run the complete API test module**

Run:

```powershell
.\VirtualEnvironment\Scripts\python.exe -m pytest backend/tests/test_api.py -v
```

Expected: PASS with no regression in existing API behavior.

- [ ] **Step 6: Commit the endpoint**

```powershell
git add backend/main.py backend/tests/test_api.py
git commit -m "feat: serve remediation PDF reports securely"
```

### Task 3: Add the Report Download Action to the Completion Modal

**Files:**
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/components/RemediationPanel.tsx`
- Modify: `backend/tests/test_frontend_remediation_contract.py`

- [ ] **Step 1: Add a failing frontend contract test**

Append to `backend/tests/test_frontend_remediation_contract.py`:

```python
def test_frontend_offers_remediation_report_download():
    panel_source = (
        REPO_ROOT / "frontend/src/components/RemediationPanel.tsx"
    ).read_text(encoding="utf-8")
    api_source = (REPO_ROOT / "frontend/src/api.ts").read_text(encoding="utf-8")

    assert "getRemediationReportURL" in api_source
    assert "`${API_BASE}/remediate/report/${reportId}`" in api_source
    assert "getRemediationReportURL(report.id)" in panel_source
    assert "Download Remediation Report" in panel_source
```

- [ ] **Step 2: Run the contract test and verify RED**

Run:

```powershell
.\VirtualEnvironment\Scripts\python.exe -m pytest backend/tests/test_frontend_remediation_contract.py -v
```

Expected: FAIL because the helper and button do not exist.

- [ ] **Step 3: Implement the URL helper and accessible action**

Add to `frontend/src/api.ts` beside `getRemediatedFileURL`:

```typescript
export function getRemediationReportURL(reportId: string): string {
  return `${API_BASE}/remediate/report/${reportId}`;
}
```

Import it in `frontend/src/components/RemediationPanel.tsx`:

```typescript
import {
  remediateDocument,
  getRemediatedFileURL,
  getRemediationReportURL,
} from '../api';
```

Allow the footer to wrap and add the secondary link before the fixed-PDF link:

```tsx
<a
  href={getRemediationReportURL(report.id)}
  download
  className="btn btn-secondary"
>
  <Download className="w-4 h-4" aria-hidden="true" />
  Download Remediation Report
</a>
```

Change the footer's existing class from `px-6 py-4 flex justify-end gap-3` to `px-6 py-4 flex flex-wrap justify-end gap-3`, and insert the link immediately after the post-remediation `Close` button and before `Download Fixed PDF`.

- [ ] **Step 4: Run the contract test and verify GREEN**

Run:

```powershell
.\VirtualEnvironment\Scripts\python.exe -m pytest backend/tests/test_frontend_remediation_contract.py -v
```

Expected: all frontend contract tests PASS.

- [ ] **Step 5: Build the frontend**

Run:

```powershell
npm run build
```

Working directory: `frontend`

Expected: TypeScript and Vite production build PASS without errors.

- [ ] **Step 6: Commit the frontend action**

```powershell
git add frontend/src/api.ts frontend/src/components/RemediationPanel.tsx backend/tests/test_frontend_remediation_contract.py
git commit -m "feat: add remediation report download action"
```

### Task 4: Full Verification and Rendered QA

**Files:**
- No committed files expected.

- [ ] **Step 1: Run the focused regression suite**

Run:

```powershell
.\VirtualEnvironment\Scripts\python.exe -m pytest backend/tests/test_remediation_report_llm_disclosure.py backend/tests/test_frontend_remediation_contract.py backend/tests/test_api.py -v
```

Expected: all selected tests PASS.

- [ ] **Step 2: Run the production frontend build again**

Run:

```powershell
npm run build
```

Working directory: `frontend`

Expected: PASS without TypeScript or Vite errors.

- [ ] **Step 3: Validate the rendered target flow with the Browser plugin**

The flow under test is: remediation-complete modal -> select `Download Remediation Report` -> authenticated `/api/remediate/report/{report_id}` request returns a PDF attachment.

Follow the Browser skill exactly: start the available backend and Vite development servers, name the browser session, acquire a tab, navigate to the app, and verify page identity, meaningful DOM content, no framework overlay, console health, screenshot evidence, and the target interaction. If a full remediation run is impractical because no test fixture is available in the UI, use browser request interception only to place the existing component in its post-remediation state; do not commit test-only production behavior.

Expected: the report action is visible in the completed state, remains visible at desktop and mobile widths, has the expected label and URL, and triggers a PDF attachment response without relevant console errors.

- [ ] **Step 4: Inspect repository state**

Run:

```powershell
git status --short
git log -4 --oneline
```

Expected: no uncommitted implementation changes; the design, generator, endpoint, and frontend commits appear at the top of history.
