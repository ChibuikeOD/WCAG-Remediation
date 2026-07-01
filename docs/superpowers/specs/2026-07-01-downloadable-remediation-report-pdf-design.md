# Downloadable Remediation Report PDF Design

## Goal

After automated remediation finishes, let the authenticated user download a human-readable PDF that documents the remediation outcome.

## Current State

The main `/remediate` flow generates a JSON remediation artifact and returns its path and filename. The completion modal only exposes the remediated document download. A legacy PDF report generator and filename-based report endpoint exist, but the main flow does not produce a PDF suitable for that endpoint, and filename-based authorization is unnecessarily indirect.

## Chosen Approach

Generate the PDF as part of the existing remediation request, return its filename in the existing remediation response fields, and serve it through a report-ID-based authenticated endpoint. Add a dedicated report download action to the post-remediation modal.

This keeps the report available immediately after remediation, avoids a second conversion or generation request, and binds authorization to the same report identity used by the remediated-document download.

## Backend Design

`generate_remediation_report_for_api` will produce a PDF instead of JSON. It will normalize the current analysis and remediation result data into a human-readable document containing:

- Report title, source document name, and generation timestamp.
- Summary counts for issues before remediation, successful fixes, failed fixes, and remaining manual issues.
- The existing DeepSeek/AI-use disclosure for Unicode mapping decisions.
- A successful-fixes section with issue identifiers, messages, and available before/after values.
- A failed-fixes section when failures exist.
- A remaining-manual-work section with rule identifiers, severity, message, and suggested fix.

The generator will use the project's existing ReportLab dependency and return a `.pdf` path. Generation failures will retain the current behavior: remediation succeeds, the failure is logged, and report fields remain absent.

A new `GET /remediate/report/{report_id}` endpoint will:

1. Require an authenticated user.
2. Confirm the report exists and belongs to that user using the same ownership rule as the remediated-file endpoint.
3. Resolve the generated remediation-report PDF for that report ID from the configured output directory.
4. Return it with `application/pdf` and an attachment filename.

The endpoint will return 403 for another user's report and 404 when the report or generated PDF does not exist. It will not accept an arbitrary filename or filesystem path.

## Frontend Design

The API client will expose `getRemediationReportURL(reportId)`. After remediation completes successfully, the modal footer will contain:

- `Close`
- `Download Remediation Report`, styled as a secondary download action
- The existing primary `Download Fixed PDF` action

The report link will use the current report ID and the browser's download behavior. The label names the artifact explicitly for screen-reader and sighted users. On narrow screens, the footer may wrap so all actions remain visible and operable.

The report button will only appear in the post-remediation state, because the report is created by the remediation request.

## Data Flow

1. The user runs automated remediation.
2. The backend applies fixes and generates the remediated document.
3. The backend generates the PDF report from the original analysis and remediation results.
4. The remediation response includes the PDF report filename through the existing report fields.
5. The completion modal exposes both document and report download actions.
6. Selecting the report action requests the authenticated report-ID endpoint and downloads the PDF.

## Testing

Backend tests will first fail against the current JSON behavior, then verify that:

- The API report generator creates a valid PDF with the required human-readable sections and key text.
- The AI-use disclosure remains present for deterministic, invoked, and unavailable cases.
- The report download endpoint serves `application/pdf` with an attachment filename.
- Missing reports and unauthorized access return the expected status codes.

Frontend contract tests will first fail, then verify that the API URL helper and `Download Remediation Report` action are present and use the report ID. The frontend production build will confirm type correctness. Rendered browser verification will exercise remediation completion through the available local/test state, confirm the report action is visible and accessible, and confirm the download request targets the expected endpoint without relevant console errors.

## Out of Scope

- User-selectable report formats or templates.
- Regenerating historical JSON remediation reports as PDFs.
- Emailing, sharing, or externally publishing reports.
- Changing the content of the remediated document itself.
