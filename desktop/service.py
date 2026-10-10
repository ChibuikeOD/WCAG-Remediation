"""Shared remediation engine, with local inputs and explicit output ownership."""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Callable
import json
import os
import shutil
import uuid


def analyze_pdf(path: Path):
    from backend.models import AccessibilityIssue, AccessibilityReport, DocumentInfo
    from backend.models import IssueStatus, Severity, WCAGPrinciple
    from backend.pdf_accessibility import PDFAccessibilityAnalyzer

    analyzer = PDFAccessibilityAnalyzer(file_path=path)
    try:
        summary = analyzer.analyze()
    finally:
        analyzer.close()
    metadata = summary.get("metadata", {})
    issues = []
    principles = {"1": WCAGPrinciple.PERCEIVABLE, "2": WCAGPrinciple.OPERABLE,
                  "3": WCAGPrinciple.UNDERSTANDABLE, "4": WCAGPrinciple.ROBUST}
    for item in summary.get("issues", []):
        criterion = item.get("wcag_criterion", item.get("rule_id", "1.3.1"))
        is_error = item.get("severity") == "error"
        issues.append(AccessibilityIssue(
            rule_id=criterion, rule_name=item.get("wcag_name", "PDF accessibility"),
            principle=principles.get(str(criterion)[0], WCAGPrinciple.PERCEIVABLE),
            wcag_level=item.get("wcag_level", "A"),
            status=IssueStatus.FAIL if is_error else IssueStatus.WARNING,
            severity=Severity.ERROR if is_error else Severity.WARNING,
            message=item.get("message", "Review required"),
            fix_suggestion=item.get("fix_suggestion", "Review the document manually"),
            automatable_fix=item.get("auto_fixable", False),
        ))
    return AccessibilityReport(
        id=str(uuid.uuid4()),
        document=DocumentInfo(filename=path.name, file_type="pdf", file_size=path.stat().st_size,
                              page_count=metadata.get("page_count"), title=metadata.get("title"),
                              language=metadata.get("language")),
        all_issues=issues, total_issues=len(issues),
        total_errors=sum(i.severity == Severity.ERROR for i in issues),
        total_warnings=sum(i.severity == Severity.WARNING for i in issues),
    )


def remediate_local(source: Path, destination: Path,
                    progress: Callable[[str], None] = lambda _: None) -> dict:
    from backend.config import settings
    from backend.remediator import PDFRemediator
    from backend.remediation_report import generate_remediation_report_for_api
    import fitz

    if not settings.LOCAL_ONLY:
        raise RuntimeError("The desktop privacy runtime must be configured before processing")
    source = source.resolve(strict=True)
    if source.suffix.lower() != ".pdf":
        raise ValueError("Choose a PDF document")
    if source.stat().st_size > settings.MAX_FILE_SIZE_MB * 1024 * 1024:
        raise ValueError(f"PDF exceeds the {settings.MAX_FILE_SIZE_MB} MB limit")
    with fitz.open(source) as document:
        if document.needs_pass:
            raise ValueError("Unlock the password-protected PDF before remediation")
        if not document.page_count or document.page_count > settings.MAX_PAGES_PDF:
            raise ValueError(f"PDF must contain 1–{settings.MAX_PAGES_PDF} pages")
    destination.mkdir(parents=True, exist_ok=True)
    run_id = str(uuid.uuid4())
    output_directory = destination / f"PDFAccess-{run_id}"
    # Stage beside the destination so publishing the completed directory is atomic.
    with TemporaryDirectory(prefix=".pdfaccess-", dir=destination) as staging_name:
        staging = Path(staging_name)
        working = staging / f"remediated_{source.name}"
        progress("Analyzing the original PDF on this device…")
        before = analyze_pdf(source)
        shutil.copy2(source, working)
        progress("Applying metadata, OCR, Unicode, tags, and structure fixes locally…")
        results = PDFRemediator(working).fix_all(
            output_path=working, report=before, original_filename=source.name,
        )
        progress("Checking the output and writing review reports…")
        after = analyze_pdf(working)
        report = generate_remediation_report_for_api(
            original_filename=source.name, file_id=run_id, report_id=run_id, file_type="pdf",
            analysis_report=before.model_dump(mode="json"),
            remediation_results=[r.model_dump(mode="json") for r in results],
            remediated_file_path=str(output_directory / working.name), output_dir=staging,
        )
        manifest = {
            "version": settings.APP_VERSION, "processing": "on-device", "cloud_ai_used": False,
            "original_filename": source.name,
            "remediated_pdf": str(output_directory / working.name),
            "report_pdf": str(output_directory / report.name),
            "output_directory": str(output_directory),
            "results": [r.model_dump(mode="json") for r in results],
            "before": before.model_dump(mode="json"), "after": after.model_dump(mode="json"),
            "review_required": True,
            "review_note": "Review reading order, tables, figure descriptions, and ambiguous glyphs. "
                           "Automated remediation does not certify WCAG or PDF/UA compliance.",
        }
        (staging / "review.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        os.replace(staging, output_directory)
    progress("Complete. The original PDF is unchanged; review the remaining findings.")
    return manifest
