"""
Generate PDF Documentation for WCAG Platform
"""
from pathlib import Path

try:
    from reportlab.lib.pagesizes import letter, A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.lib.colors import HexColor, black, white, grey
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
        PageBreak, ListFlowable, ListItem, Preformatted
    )
    from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
    HAS_REPORTLAB = True
except ImportError:
    HAS_REPORTLAB = False
    print("Installing reportlab...")
    import subprocess
    subprocess.run(["pip", "install", "reportlab", "-q"])
    from reportlab.lib.pagesizes import letter, A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.lib.colors import HexColor, black, white, grey
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
        PageBreak, ListFlowable, ListItem, Preformatted
    )
    from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY


def create_pdf():
    """Generate the documentation PDF."""
    
    output_path = Path("WCAG_Platform_Documentation.pdf")
    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=letter,
        rightMargin=0.75*inch,
        leftMargin=0.75*inch,
        topMargin=0.75*inch,
        bottomMargin=0.75*inch
    )
    
    # Styles
    styles = getSampleStyleSheet()
    
    # Custom styles
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        spaceAfter=30,
        textColor=HexColor('#0891b2'),
        alignment=TA_CENTER
    )
    
    h1_style = ParagraphStyle(
        'CustomH1',
        parent=styles['Heading1'],
        fontSize=18,
        spaceBefore=20,
        spaceAfter=10,
        textColor=HexColor('#1e3a5f')
    )
    
    h2_style = ParagraphStyle(
        'CustomH2',
        parent=styles['Heading2'],
        fontSize=14,
        spaceBefore=15,
        spaceAfter=8,
        textColor=HexColor('#374151')
    )
    
    h3_style = ParagraphStyle(
        'CustomH3',
        parent=styles['Heading3'],
        fontSize=12,
        spaceBefore=10,
        spaceAfter=6,
        textColor=HexColor('#4b5563')
    )
    
    body_style = ParagraphStyle(
        'CustomBody',
        parent=styles['Normal'],
        fontSize=10,
        spaceAfter=8,
        alignment=TA_JUSTIFY
    )
    
    code_style = ParagraphStyle(
        'CodeStyle',
        parent=styles['Code'],
        fontSize=8,
        fontName='Courier',
        backColor=HexColor('#f3f4f6'),
        leftIndent=10,
        rightIndent=10,
        spaceBefore=5,
        spaceAfter=5
    )
    
    # Build content
    story = []
    
    # Title Page
    story.append(Spacer(1, 2*inch))
    story.append(Paragraph("WCAG 2.2 Accessibility", title_style))
    story.append(Paragraph("Remediation Platform", title_style))
    story.append(Spacer(1, 0.5*inch))
    story.append(Paragraph("Technical Documentation", ParagraphStyle(
        'Subtitle', parent=styles['Normal'], fontSize=16, alignment=TA_CENTER, textColor=grey
    )))
    story.append(Spacer(1, 1*inch))
    story.append(Paragraph("Version 1.0.0", ParagraphStyle(
        'Version', parent=styles['Normal'], fontSize=12, alignment=TA_CENTER
    )))
    story.append(PageBreak())
    
    # Table of Contents
    story.append(Paragraph("Table of Contents", h1_style))
    toc_items = [
        "1. Overview",
        "2. Architecture",
        "3. Module Descriptions",
        "4. PDF Accessibility Checks",
        "5. API Endpoints",
        "6. Data Models",
        "7. Usage Examples",
        "8. Dependencies"
    ]
    for item in toc_items:
        story.append(Paragraph(f"• {item}", body_style))
    story.append(PageBreak())
    
    # Section 1: Overview
    story.append(Paragraph("1. Overview", h1_style))
    story.append(Paragraph(
        "The <b>WCAG 2.2 Accessibility Remediation Platform</b> is an automated accessibility "
        "audit engine designed to analyze PDF documents against the Web Content Accessibility "
        "Guidelines (WCAG) 2.2 standard.",
        body_style
    ))
    story.append(Spacer(1, 10))
    
    story.append(Paragraph("Key Capabilities:", h3_style))
    capabilities = [
        "Upload and analyze PDF documents for accessibility compliance",
        "Detect WCAG violations with specific criterion references",
        "Apply automated fixes (title, language, bookmarks)",
        "Generate detailed compliance reports",
        "Support for PDF/UA (ISO 14289-1) compliance checking"
    ]
    for cap in capabilities:
        story.append(Paragraph(f"• {cap}", body_style))
    
    story.append(Spacer(1, 20))
    
    # Section 2: Architecture
    story.append(Paragraph("2. Architecture", h1_style))
    story.append(Paragraph(
        "The platform follows a modular architecture with clear separation of concerns:",
        body_style
    ))
    
    arch_data = [
        ["Layer", "Component", "Purpose"],
        ["API", "FastAPI (main.py)", "REST endpoints for all operations"],
        ["Analysis", "PDFAccessibilityAnalyzer", "WCAG compliance checking"],
        ["Rules", "RulesEngine", "87 WCAG 2.2 rules loaded from JSONC"],
        ["Parsing", "PDFParser", "Document structure extraction"],
        ["Remediation", "PDFRemediator", "Automated fix application"],
    ]
    
    arch_table = Table(arch_data, colWidths=[1.2*inch, 2*inch, 3*inch])
    arch_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), HexColor('#0891b2')),
        ('TEXTCOLOR', (0, 0), (-1, 0), white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('GRID', (0, 0), (-1, -1), 0.5, grey),
        ('BACKGROUND', (0, 1), (-1, -1), HexColor('#f9fafb')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [HexColor('#ffffff'), HexColor('#f3f4f6')]),
        ('PADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(arch_table)
    story.append(Spacer(1, 20))
    
    # Section 3: Modules
    story.append(Paragraph("3. Module Descriptions", h1_style))
    
    # 3.1 main.py
    story.append(Paragraph("3.1 backend/main.py - FastAPI Application", h2_style))
    story.append(Paragraph(
        "The main application entry point that defines all REST API endpoints for file upload, "
        "analysis, remediation, and rule management.",
        body_style
    ))
    
    endpoints_data = [
        ["Endpoint", "Method", "Description"],
        ["/upload", "POST", "Upload PDF/HTML files for analysis"],
        ["/pdf/analyze", "POST", "Detailed PDF accessibility analysis"],
        ["/pdf/remediate", "POST", "Apply automated fixes to PDF"],
        ["/pdf/download/{id}", "GET", "Download processed PDF"],
        ["/rules", "GET", "List all WCAG rules"],
        ["/health", "GET", "Server health check"],
    ]
    
    ep_table = Table(endpoints_data, colWidths=[1.8*inch, 0.8*inch, 3.5*inch])
    ep_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), HexColor('#059669')),
        ('TEXTCOLOR', (0, 0), (-1, 0), white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('GRID', (0, 0), (-1, -1), 0.5, grey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [HexColor('#ffffff'), HexColor('#ecfdf5')]),
        ('PADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(ep_table)
    story.append(Spacer(1, 15))
    
    # 3.2 pdf_accessibility.py
    story.append(Paragraph("3.2 backend/pdf_accessibility.py - PDF Analyzer", h2_style))
    story.append(Paragraph(
        "The core PDF accessibility analysis module containing the PDFAccessibilityAnalyzer "
        "and PDFRemediator classes.",
        body_style
    ))
    
    story.append(Paragraph("<b>PDFAccessibilityAnalyzer Methods:</b>", body_style))
    analyzer_methods = [
        ("analyze()", "Performs full accessibility analysis"),
        ("_check_title()", "WCAG 2.4.2 - Verifies document has title"),
        ("_check_language()", "WCAG 3.1.1 - Checks language specification"),
        ("_check_tagged()", "WCAG 1.3.1 - Verifies PDF is tagged"),
        ("_check_alt_text()", "WCAG 1.1.1 - Checks images for alt text"),
        ("_check_reading_order()", "WCAG 1.3.2 - Analyzes reading sequence"),
        ("_check_tables()", "WCAG 1.3.1 - Validates table headers"),
        ("_check_headings()", "WCAG 2.4.6 - Checks heading structure"),
        ("_check_bookmarks()", "WCAG 2.4.5 - Verifies navigation aids"),
    ]
    
    for method, desc in analyzer_methods:
        story.append(Paragraph(f"• <font face='Courier' size='9'>{method}</font> - {desc}", body_style))
    
    story.append(Spacer(1, 10))
    story.append(Paragraph("<b>PDFRemediator Methods:</b>", body_style))
    story.append(Paragraph("• <font face='Courier' size='9'>fix_metadata(title, language)</font> - Sets document properties", body_style))
    story.append(Paragraph("• <font face='Courier' size='9'>generate_bookmarks_from_headings()</font> - Creates navigation", body_style))
    
    story.append(Spacer(1, 15))
    
    # 3.3 rules_engine.py
    story.append(Paragraph("3.3 backend/rules_engine.py - Rules Engine", h2_style))
    story.append(Paragraph(
        "The core engine that loads and executes 87 WCAG rules from JSONC configuration files. "
        "Supports rule filtering by level (A/AA/AAA), principle, and automation capability.",
        body_style
    ))
    
    story.append(Paragraph("<b>Key Methods:</b>", body_style))
    story.append(Paragraph("• <font face='Courier' size='9'>get_all_rules()</font> - Returns all loaded rules", body_style))
    story.append(Paragraph("• <font face='Courier' size='9'>get_rules_by_level(level)</font> - Filter by WCAG level", body_style))
    story.append(Paragraph("• <font face='Courier' size='9'>get_rule_by_id(id)</font> - Get specific rule (e.g., '1.1.1')", body_style))
    story.append(Paragraph("• <font face='Courier' size='9'>analyze_html(content, info, level)</font> - Run checks on HTML", body_style))
    
    story.append(PageBreak())
    
    # Section 4: PDF Checks
    story.append(Paragraph("4. PDF Accessibility Checks", h1_style))
    story.append(Paragraph(
        "The following checks are performed on PDF documents:",
        body_style
    ))
    
    checks_data = [
        ["Check", "WCAG", "Level", "Auto-Fix"],
        ["Document Title", "2.4.2", "A", "✓ Yes"],
        ["Document Language", "3.1.1", "A", "✓ Yes"],
        ["Tagged PDF Structure", "1.3.1", "A", "✗ No"],
        ["Alt Text on Images", "1.1.1", "A", "✗ No"],
        ["Reading Order", "1.3.2", "A", "✗ No"],
        ["Table Headers", "1.3.1", "A", "✗ No"],
        ["Heading Structure", "2.4.6", "AA", "✗ No"],
        ["Navigation Bookmarks", "2.4.5", "AA", "✓ Yes"],
        ["Link Tagging", "2.4.4", "A", "✗ No"],
        ["Form Field Labels", "3.3.2", "A", "✗ No"],
        ["Scanned Image Content", "1.4.5", "AA", "✗ No"],
    ]
    
    checks_table = Table(checks_data, colWidths=[2.5*inch, 1*inch, 0.8*inch, 1*inch])
    checks_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), HexColor('#7c3aed')),
        ('TEXTCOLOR', (0, 0), (-1, 0), white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
        ('GRID', (0, 0), (-1, -1), 0.5, grey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [HexColor('#ffffff'), HexColor('#f5f3ff')]),
        ('PADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(checks_table)
    story.append(Spacer(1, 20))
    
    # Section 5: API Reference
    story.append(Paragraph("5. API Endpoints Reference", h1_style))
    
    story.append(Paragraph("5.1 POST /upload", h2_style))
    story.append(Paragraph("Upload a PDF file for analysis.", body_style))
    story.append(Paragraph("<b>Request:</b> multipart/form-data with 'file' field", body_style))
    story.append(Paragraph("<b>Response:</b> { success, file_id, file_type, original_filename }", body_style))
    
    story.append(Paragraph("5.2 POST /pdf/analyze", h2_style))
    story.append(Paragraph("Run comprehensive PDF accessibility analysis.", body_style))
    story.append(Paragraph("<b>Parameters:</b> file_id (query string)", body_style))
    story.append(Paragraph("<b>Response:</b> { metadata, structure, compliance, summary, issues[] }", body_style))
    
    story.append(Paragraph("5.3 POST /pdf/remediate", h2_style))
    story.append(Paragraph("Apply automated fixes to a PDF document.", body_style))
    story.append(Paragraph("<b>Parameters:</b> file_id, title, language, add_bookmarks", body_style))
    story.append(Paragraph("<b>Response:</b> { success, changes[], total_changes }", body_style))
    
    story.append(Paragraph("5.4 GET /pdf/download/{file_id}", h2_style))
    story.append(Paragraph("Download the processed PDF file.", body_style))
    story.append(Paragraph("<b>Response:</b> PDF file stream", body_style))
    
    story.append(PageBreak())
    
    # Section 6: Data Models
    story.append(Paragraph("6. Data Models", h1_style))
    
    story.append(Paragraph("6.1 Analysis Response Structure", h2_style))
    code_block = """
{
  "metadata": {
    "title": "Document Title",
    "language": "en",
    "page_count": 10,
    "is_tagged": true/false,
    "has_bookmarks": true/false,
    "pdf_version": "1.7"
  },
  "structure": {
    "has_structure_tree": true/false,
    "figure_count": 5,
    "figures_with_alt": 3,
    "table_count": 2,
    "heading_count": {"H1": 1, "H2": 4}
  },
  "compliance": {
    "wcag_a_compliant": true/false,
    "wcag_aa_compliant": true/false,
    "pdf_ua_compliant": true/false
  },
  "summary": {
    "total_issues": 3,
    "errors": 2,
    "warnings": 1,
    "auto_fixable": 1
  },
  "issues": [
    {
      "type": "missing_title",
      "wcag_criterion": "2.4.2",
      "wcag_name": "Page Titled",
      "severity": "error",
      "message": "PDF is missing title",
      "fix_suggestion": "Add title in properties",
      "auto_fixable": true
    }
  ]
}
"""
    story.append(Preformatted(code_block, code_style))
    
    story.append(Spacer(1, 20))
    
    # Section 7: Usage
    story.append(Paragraph("7. Usage Examples (PowerShell)", h1_style))
    
    story.append(Paragraph("7.1 Upload and Analyze PDF", h2_style))
    ps_code = """
# Upload PDF
$upload = Invoke-RestMethod -Uri "http://localhost:8000/upload" `
    -Method Post -Form @{ file = Get-Item "document.pdf" }

# Analyze
$analysis = Invoke-RestMethod `
    -Uri "http://localhost:8000/pdf/analyze?file_id=$($upload.file_id)" `
    -Method Post

# View results
$analysis.issues | Format-Table
"""
    story.append(Preformatted(ps_code, code_style))
    
    story.append(Paragraph("7.2 Remediate PDF", h2_style))
    ps_code2 = """
# Apply fixes
Invoke-RestMethod `
    -Uri "http://localhost:8000/pdf/remediate?file_id=$fileId&title=My%20Doc&language=en" `
    -Method Post

# Download fixed file
Invoke-WebRequest `
    -Uri "http://localhost:8000/pdf/download/$fileId" `
    -OutFile "fixed.pdf"
"""
    story.append(Preformatted(ps_code2, code_style))
    
    story.append(PageBreak())
    
    # Section 8: Dependencies
    story.append(Paragraph("8. Dependencies", h1_style))
    
    deps_data = [
        ["Package", "Version", "Purpose"],
        ["FastAPI", "0.109+", "REST API framework"],
        ["uvicorn", "0.27+", "ASGI web server"],
        ["PyMuPDF", "1.23+", "PDF parsing and analysis"],
        ["pikepdf", "8.11+", "PDF metadata editing"],
        ["beautifulsoup4", "4.12+", "HTML parsing"],
        ["pydantic", "2.6+", "Data validation"],
        ["aiofiles", "23.2+", "Async file operations"],
    ]
    
    deps_table = Table(deps_data, colWidths=[2*inch, 1*inch, 3*inch])
    deps_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), HexColor('#dc2626')),
        ('TEXTCOLOR', (0, 0), (-1, 0), white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('GRID', (0, 0), (-1, -1), 0.5, grey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [HexColor('#ffffff'), HexColor('#fef2f2')]),
        ('PADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(deps_table)
    
    story.append(Spacer(1, 30))
    story.append(Paragraph("Installation:", h3_style))
    story.append(Preformatted(
        "pip install fastapi uvicorn PyMuPDF pikepdf beautifulsoup4 pydantic aiofiles",
        code_style
    ))
    
    story.append(Spacer(1, 30))
    story.append(Paragraph("Running the Server:", h3_style))
    story.append(Preformatted(
        "python run_backend.py\n\n# Access at:\n# API: http://localhost:8000\n# Docs: http://localhost:8000/docs",
        code_style
    ))
    
    # Build PDF
    doc.build(story)
    print(f"\n✅ PDF generated: {output_path.absolute()}")
    return output_path


if __name__ == "__main__":
    create_pdf()





