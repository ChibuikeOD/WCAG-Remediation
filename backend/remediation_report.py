"""
Remediation Report Generator

Generates detailed PDF reports documenting all accessibility fixes applied to a document.
"""
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)

try:
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.lib.colors import HexColor, black, white, grey, green, red
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
        PageBreak, Image
    )
    from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    HAS_REPORTLAB = True
except ImportError:
    HAS_REPORTLAB = False
    logger.warning("reportlab not installed - PDF report generation disabled")


@dataclass
class RemediationChange:
    """A single remediation change."""
    change_type: str
    wcag_criterion: str
    wcag_name: str
    description: str
    old_value: Optional[str]
    new_value: str
    success: bool
    error_message: Optional[str] = None


@dataclass 
class RemediationReportData:
    """Data for a remediation report."""
    original_filename: str
    file_id: str
    analysis_date: datetime
    remediation_date: datetime
    
    # Before remediation
    issues_before: int
    errors_before: int
    warnings_before: int
    
    # After remediation
    issues_fixed: int
    issues_remaining: int
    
    # Compliance status
    was_wcag_a_compliant: bool
    was_wcag_aa_compliant: bool
    is_wcag_a_compliant: bool
    is_wcag_aa_compliant: bool
    
    # Changes made
    changes: List[RemediationChange]
    
    # Issues that couldn't be fixed
    manual_fixes_needed: List[Dict[str, Any]]


class RemediationReportGenerator:
    """
    Generates PDF remediation reports.
    """
    
    def __init__(self, output_dir: Path):
        """Initialize with output directory."""
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def generate_report(self, data: RemediationReportData) -> Path:
        """
        Generate a PDF remediation report.
        
        Args:
            data: Remediation report data
            
        Returns:
            Path to generated PDF
        """
        if not HAS_REPORTLAB:
            # Generate JSON report instead
            return self._generate_json_report(data)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"Remediation_Report_{timestamp}.pdf"
        output_path = self.output_dir / filename
        
        doc = SimpleDocTemplate(
            str(output_path),
            pagesize=letter,
            rightMargin=0.75*inch,
            leftMargin=0.75*inch,
            topMargin=0.75*inch,
            bottomMargin=0.75*inch
        )
        
        styles = getSampleStyleSheet()
        
        # Custom styles
        title_style = ParagraphStyle(
            'ReportTitle',
            parent=styles['Heading1'],
            fontSize=20,
            spaceAfter=20,
            textColor=HexColor('#0891b2'),
            alignment=TA_CENTER
        )
        
        h1_style = ParagraphStyle(
            'H1',
            parent=styles['Heading1'],
            fontSize=14,
            spaceBefore=15,
            spaceAfter=10,
            textColor=HexColor('#1e3a5f')
        )
        
        h2_style = ParagraphStyle(
            'H2',
            parent=styles['Heading2'],
            fontSize=12,
            spaceBefore=10,
            spaceAfter=6,
            textColor=HexColor('#374151')
        )
        
        body_style = ParagraphStyle(
            'Body',
            parent=styles['Normal'],
            fontSize=10,
            spaceAfter=6
        )
        
        success_style = ParagraphStyle(
            'Success',
            parent=styles['Normal'],
            fontSize=10,
            textColor=HexColor('#059669')
        )
        
        error_style = ParagraphStyle(
            'Error',
            parent=styles['Normal'],
            fontSize=10,
            textColor=HexColor('#dc2626')
        )
        
        story = []
        
        # Header
        story.append(Paragraph("PDF Accessibility Remediation Report", title_style))
        story.append(Spacer(1, 10))
        
        # Document info
        story.append(Paragraph("Document Information", h1_style))
        
        info_data = [
            ["Property", "Value"],
            ["Original File", data.original_filename],
            ["File ID", data.file_id[:8] + "..."],
            ["Analysis Date", data.analysis_date.strftime("%Y-%m-%d %H:%M:%S")],
            ["Remediation Date", data.remediation_date.strftime("%Y-%m-%d %H:%M:%S")],
        ]
        
        info_table = Table(info_data, colWidths=[2*inch, 4*inch])
        info_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), HexColor('#f3f4f6')),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('GRID', (0, 0), (-1, -1), 0.5, grey),
            ('PADDING', (0, 0), (-1, -1), 8),
            ('BACKGROUND', (0, 1), (0, -1), HexColor('#f9fafb')),
        ]))
        story.append(info_table)
        story.append(Spacer(1, 20))
        
        # Summary
        story.append(Paragraph("Remediation Summary", h1_style))
        
        # Before/After comparison
        summary_data = [
            ["Metric", "Before", "After", "Change"],
            ["Total Issues", str(data.issues_before), str(data.issues_remaining), f"-{data.issues_fixed}"],
            ["Errors", str(data.errors_before), str(data.issues_remaining), ""],
            ["WCAG A Compliant", "Yes" if data.was_wcag_a_compliant else "No", 
             "Yes" if data.is_wcag_a_compliant else "No", ""],
            ["WCAG AA Compliant", "Yes" if data.was_wcag_aa_compliant else "No",
             "Yes" if data.is_wcag_aa_compliant else "No", ""],
        ]
        
        summary_table = Table(summary_data, colWidths=[2*inch, 1.2*inch, 1.2*inch, 1.2*inch])
        summary_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), HexColor('#0891b2')),
            ('TEXTCOLOR', (0, 0), (-1, 0), white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
            ('GRID', (0, 0), (-1, -1), 0.5, grey),
            ('PADDING', (0, 0), (-1, -1), 8),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [HexColor('#ffffff'), HexColor('#f0fdfa')]),
        ]))
        story.append(summary_table)
        story.append(Spacer(1, 20))
        
        # Changes Applied
        story.append(Paragraph("Changes Applied", h1_style))
        
        if data.changes:
            for i, change in enumerate(data.changes, 1):
                status_color = '#059669' if change.success else '#dc2626'
                status_text = "✓ SUCCESS" if change.success else "✗ FAILED"
                
                story.append(Paragraph(
                    f"<b>{i}. [{change.wcag_criterion}] {change.wcag_name}</b>",
                    h2_style
                ))
                
                change_data = [
                    ["Status", f'<font color="{status_color}">{status_text}</font>'],
                    ["Change Type", change.change_type.replace("_", " ").title()],
                    ["Description", change.description],
                ]
                
                if change.old_value:
                    change_data.append(["Previous Value", change.old_value or "(none)"])
                change_data.append(["New Value", change.new_value])
                
                if change.error_message:
                    change_data.append(["Error", change.error_message])
                
                # Convert to paragraphs for HTML support
                change_data_formatted = []
                for row in change_data:
                    change_data_formatted.append([
                        row[0],
                        Paragraph(row[1], body_style)
                    ])
                
                change_table = Table(change_data_formatted, colWidths=[1.5*inch, 4.5*inch])
                change_table.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (0, -1), HexColor('#f3f4f6')),
                    ('FONTSIZE', (0, 0), (-1, -1), 9),
                    ('GRID', (0, 0), (-1, -1), 0.5, HexColor('#e5e7eb')),
                    ('PADDING', (0, 0), (-1, -1), 6),
                    ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ]))
                story.append(change_table)
                story.append(Spacer(1, 10))
        else:
            story.append(Paragraph("No changes were applied.", body_style))
        
        story.append(Spacer(1, 20))
        
        # Remaining Issues (Manual Fixes Needed)
        if data.manual_fixes_needed:
            story.append(Paragraph("Remaining Issues (Manual Fix Required)", h1_style))
            story.append(Paragraph(
                "The following issues require manual intervention and cannot be automatically fixed:",
                body_style
            ))
            story.append(Spacer(1, 10))
            
            for i, issue in enumerate(data.manual_fixes_needed, 1):
                story.append(Paragraph(
                    f"<b>{i}. [{issue.get('wcag_criterion', 'N/A')}] {issue.get('wcag_name', 'Unknown')}</b>",
                    h2_style
                ))
                story.append(Paragraph(f"Issue: {issue.get('message', 'N/A')}", body_style))
                story.append(Paragraph(
                    f"<i>How to fix: {issue.get('fix_suggestion', 'N/A')}</i>",
                    ParagraphStyle('Italic', parent=body_style, textColor=HexColor('#6b7280'))
                ))
                story.append(Spacer(1, 8))
        
        # Footer
        story.append(Spacer(1, 30))
        story.append(Paragraph(
            f"Report generated by WCAG 2.2 Accessibility Remediation Platform",
            ParagraphStyle('Footer', parent=body_style, fontSize=8, textColor=grey, alignment=TA_CENTER)
        ))
        story.append(Paragraph(
            f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            ParagraphStyle('Footer', parent=body_style, fontSize=8, textColor=grey, alignment=TA_CENTER)
        ))
        
        # Build PDF
        doc.build(story)
        logger.info(f"Generated remediation report: {output_path}")
        
        return output_path
    
    def _generate_json_report(self, data: RemediationReportData) -> Path:
        """Generate JSON report as fallback."""
        import json
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"Remediation_Report_{timestamp}.json"
        output_path = self.output_dir / filename
        
        report = {
            "report_type": "remediation",
            "generated_at": datetime.now().isoformat(),
            "document": {
                "filename": data.original_filename,
                "file_id": data.file_id,
                "analysis_date": data.analysis_date.isoformat(),
                "remediation_date": data.remediation_date.isoformat(),
            },
            "summary": {
                "issues_before": data.issues_before,
                "errors_before": data.errors_before,
                "warnings_before": data.warnings_before,
                "issues_fixed": data.issues_fixed,
                "issues_remaining": data.issues_remaining,
            },
            "compliance": {
                "before": {
                    "wcag_a": data.was_wcag_a_compliant,
                    "wcag_aa": data.was_wcag_aa_compliant,
                },
                "after": {
                    "wcag_a": data.is_wcag_a_compliant,
                    "wcag_aa": data.is_wcag_aa_compliant,
                }
            },
            "changes": [
                {
                    "type": c.change_type,
                    "wcag_criterion": c.wcag_criterion,
                    "wcag_name": c.wcag_name,
                    "description": c.description,
                    "old_value": c.old_value,
                    "new_value": c.new_value,
                    "success": c.success,
                    "error": c.error_message,
                }
                for c in data.changes
            ],
            "manual_fixes_needed": data.manual_fixes_needed,
        }
        
        with open(output_path, 'w') as f:
            json.dump(report, f, indent=2)
        
        return output_path


def generate_remediation_report(
    original_filename: str,
    file_id: str,
    analysis_result: Dict[str, Any],
    remediation_result: Dict[str, Any],
    output_dir: Path
) -> Path:
    """
    Convenience function to generate a remediation report.
    
    Args:
        original_filename: Original PDF filename
        file_id: File ID
        analysis_result: Results from PDF analysis (before)
        remediation_result: Results from remediation
        output_dir: Where to save the report
        
    Returns:
        Path to generated report
    """
    # Build change objects
    changes = []
    
    for change in remediation_result.get("changes", []):
        change_type = change.get("type", "unknown")
        
        # Map change types to WCAG criteria
        wcag_mapping = {
            "set_title": ("2.4.2", "Page Titled"),
            "set_language": ("3.1.1", "Language of Page"),
            "add_bookmarks": ("2.4.5", "Multiple Ways"),
            "set_author": ("N/A", "Document Metadata"),
        }
        
        wcag_criterion, wcag_name = wcag_mapping.get(change_type, ("N/A", "Unknown"))
        
        changes.append(RemediationChange(
            change_type=change_type,
            wcag_criterion=wcag_criterion,
            wcag_name=wcag_name,
            description=f"Set {change_type.replace('_', ' ')} to '{change.get('value', 'N/A')}'",
            old_value=None,
            new_value=str(change.get("value", change.get("count", "N/A"))),
            success=True,
            error_message=None
        ))
    
    # Get issues that still need manual fixes
    manual_fixes = []
    for issue in analysis_result.get("issues", []):
        if not issue.get("auto_fixable", False):
            manual_fixes.append(issue)
    
    # Build report data
    data = RemediationReportData(
        original_filename=original_filename,
        file_id=file_id,
        analysis_date=datetime.now(),
        remediation_date=datetime.now(),
        issues_before=analysis_result.get("summary", {}).get("total_issues", 0),
        errors_before=analysis_result.get("summary", {}).get("errors", 0),
        warnings_before=analysis_result.get("summary", {}).get("warnings", 0),
        issues_fixed=len(changes),
        issues_remaining=len(manual_fixes),
        was_wcag_a_compliant=analysis_result.get("compliance", {}).get("wcag_a_compliant", False),
        was_wcag_aa_compliant=analysis_result.get("compliance", {}).get("wcag_aa_compliant", False),
        is_wcag_a_compliant=len([m for m in manual_fixes if m.get("wcag_level") == "A"]) == 0,
        is_wcag_aa_compliant=len(manual_fixes) == 0,
        changes=changes,
        manual_fixes_needed=manual_fixes
    )
    
    generator = RemediationReportGenerator(output_dir)
    return generator.generate_report(data)


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
    """
    Generate a human-readable PDF remediation report for the main `/remediate` API.
    """
    if not HAS_REPORTLAB:
        raise RuntimeError(
            "ReportLab is required to generate PDF remediation reports."
        )

    from html import escape

    output_dir.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now()
    timestamp = generated_at.strftime("%Y%m%d_%H%M%S")
    filename = f"Remediation_Report_{report_id}_{timestamp}.pdf"
    output_path = output_dir / filename

    # Minimal before/after summary using what the API already has
    issues_before = len(analysis_report.get("all_issues", []))
    fixed = [r for r in remediation_results if r.get("success")]
    failed = [r for r in remediation_results if not r.get("success")]

    unicode_result = next(
        (r for r in remediation_results if r.get("issue_id") == "pdf-unicode-mapping"),
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
            "id": i.get("id"),
            "rule_id": i.get("rule_id"),
            "rule_name": i.get("rule_name"),
            "severity": i.get("severity"),
            "message": i.get("message"),
            "fix_suggestion": i.get("fix_suggestion"),
        }
        for i in analysis_report.get("all_issues", [])
        if not i.get("automatable_fix", False)
    ]

    styles = getSampleStyleSheet()
    unicode_font_name = "STSong-Light"
    if unicode_font_name not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(UnicodeCIDFont(unicode_font_name))
    title_style = ParagraphStyle(
        "ApiReportTitle",
        parent=styles["Title"],
        fontName=unicode_font_name,
        fontSize=20,
        leading=24,
        textColor=HexColor("#0e7490"),
        spaceAfter=18,
    )
    section_style = ParagraphStyle(
        "ApiReportSection",
        parent=styles["Heading2"],
        fontName=unicode_font_name,
        fontSize=14,
        leading=17,
        textColor=HexColor("#164e63"),
        spaceBefore=14,
        spaceAfter=8,
    )
    item_style = ParagraphStyle(
        "ApiReportItem",
        parent=styles["BodyText"],
        fontName=unicode_font_name,
        fontSize=10,
        leading=14,
        spaceAfter=4,
    )

    def dynamic_paragraph(value: Any, style: ParagraphStyle = item_style) -> Paragraph:
        """Create a Paragraph whose dynamic content cannot be parsed as markup."""
        return Paragraph(escape(str(value), quote=True), style)

    def add_result_details(story: List[Any], results: List[Dict[str, Any]]) -> None:
        if not results:
            story.append(Paragraph("None.", item_style))
            return

        for result in results:
            story.append(dynamic_paragraph(f"Issue ID: {result.get('issue_id', 'N/A')}"))
            story.append(dynamic_paragraph(f"Message: {result.get('message', 'N/A')}"))
            details = result.get("details") or {}
            details_old_value = details.get(
                "original_value", details.get("old_value")
            )
            old_value = result.get(
                "original_value",
                result.get("old_value", details_old_value),
            )
            new_value = result.get("new_value", details.get("new_value"))
            if old_value is not None:
                story.append(dynamic_paragraph(f"Previous value: {old_value}"))
            if new_value is not None:
                story.append(dynamic_paragraph(f"New value: {new_value}"))
            story.append(Spacer(1, 6))

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=letter,
        rightMargin=0.7 * inch,
        leftMargin=0.7 * inch,
        topMargin=0.7 * inch,
        bottomMargin=0.7 * inch,
        title="PDF Accessibility Remediation Report",
    )
    story: List[Any] = [
        Paragraph("PDF Accessibility Remediation Report", title_style),
        Paragraph("Document Information", section_style),
        dynamic_paragraph(f"Document name: {original_filename}"),
        dynamic_paragraph(f"Report ID: {report_id}"),
        dynamic_paragraph(f"File ID: {file_id}"),
        dynamic_paragraph(f"File type: {file_type}"),
        dynamic_paragraph(f"Generated: {generated_at.strftime('%Y-%m-%d %H:%M:%S')}"),
        dynamic_paragraph(
            f"Remediated file: {remediated_file_path or 'Not available'}"
        ),
        Paragraph("Summary", section_style),
    ]

    summary_rows = [
        ("Issues before remediation", issues_before),
        ("Successful fixes", len(fixed)),
        ("Failed fixes", len(failed)),
        ("Manual work remaining", len(manual_remaining)),
    ]
    summary_table = Table(
        [
            [dynamic_paragraph(label), dynamic_paragraph(value)]
            for label, value in summary_rows
        ],
        colWidths=[3.8 * inch, 1.4 * inch],
    )
    summary_table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.5, HexColor("#cbd5e1")),
                ("BACKGROUND", (0, 0), (0, -1), HexColor("#f1f5f9")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.extend(
        [
            summary_table,
            Paragraph("AI-Use Disclosure", section_style),
            dynamic_paragraph(llm_disclosure),
            Paragraph("Successful Fixes", section_style),
        ]
    )
    add_result_details(story, fixed)
    story.append(Paragraph("Failed Fixes", section_style))
    add_result_details(story, failed)

    story.append(Paragraph("Remaining Manual Work", section_style))
    if not manual_remaining:
        story.append(Paragraph("None.", item_style))
    else:
        for issue in manual_remaining:
            story.append(dynamic_paragraph(f"Issue ID: {issue.get('id', 'N/A')}"))
            story.append(dynamic_paragraph(f"Rule: {issue.get('rule_id', 'N/A')}"))
            story.append(dynamic_paragraph(f"Name: {issue.get('rule_name', 'N/A')}"))
            story.append(dynamic_paragraph(f"Severity: {issue.get('severity', 'N/A')}"))
            story.append(dynamic_paragraph(f"Message: {issue.get('message', 'N/A')}"))
            story.append(
                dynamic_paragraph(
                    f"Suggested manual fix: {issue.get('fix_suggestion', 'N/A')}"
                )
            )
            story.append(Spacer(1, 6))

    doc.build(story)

    logger.info(f"Generated remediation report: {output_path}")
    return output_path





