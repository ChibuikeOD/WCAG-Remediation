#!/usr/bin/env python3
"""
Generate a PDF report of all implemented WCAG rules.
Shows rules, WCAG references, and code locations.
"""

import json
import re
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any

# Try to import PDF library
try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter, A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    HAS_REPORTLAB = True
except ImportError:
    HAS_REPORTLAB = False
    print("Installing reportlab...")
    import subprocess
    subprocess.run(["pip", "install", "reportlab"], check=True)
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter, A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
    from reportlab.lib.enums import TA_CENTER, TA_LEFT


def load_rules_from_jsonc(file_path: Path) -> List[Dict]:
    """Load rules from a JSONC file, handling comments."""
    content = file_path.read_text(encoding='utf-8')
    
    # Remove single-line comments
    content = re.sub(r'//.*$', '', content, flags=re.MULTILINE)
    # Remove multi-line comments
    content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)
    # Remove trailing commas
    content = re.sub(r',(\s*[}\]])', r'\1', content)
    
    try:
        data = json.loads(content)
        return data.get('rules', [])
    except json.JSONDecodeError as e:
        print(f"Error parsing {file_path.name}: {e}")
        return []


def get_wcag_url(criterion_id: str) -> str:
    """Generate WCAG Understanding document URL."""
    # Map criterion ID to slug
    slugs = {
        "1.1.1": "non-text-content",
        "1.2.1": "audio-only-and-video-only-prerecorded",
        "1.2.2": "captions-prerecorded",
        "1.2.3": "audio-description-or-media-alternative-prerecorded",
        "1.2.4": "captions-live",
        "1.2.5": "audio-description-prerecorded",
        "1.2.6": "sign-language-prerecorded",
        "1.2.7": "extended-audio-description-prerecorded",
        "1.2.8": "media-alternative-prerecorded",
        "1.2.9": "audio-only-live",
        "1.3.1": "info-and-relationships",
        "1.3.2": "meaningful-sequence",
        "1.3.3": "sensory-characteristics",
        "1.3.4": "orientation",
        "1.3.5": "identify-input-purpose",
        "1.3.6": "identify-purpose",
        "1.4.1": "use-of-color",
        "1.4.2": "audio-control",
        "1.4.3": "contrast-minimum",
        "1.4.4": "resize-text",
        "1.4.5": "images-of-text",
        "1.4.6": "contrast-enhanced",
        "1.4.7": "low-or-no-background-audio",
        "1.4.8": "visual-presentation",
        "1.4.9": "images-of-text-no-exception",
        "1.4.10": "reflow",
        "1.4.11": "non-text-contrast",
        "1.4.12": "text-spacing",
        "1.4.13": "content-on-hover-or-focus",
        "2.1.1": "keyboard",
        "2.1.2": "no-keyboard-trap",
        "2.1.3": "keyboard-no-exception",
        "2.1.4": "character-key-shortcuts",
        "2.2.1": "timing-adjustable",
        "2.2.2": "pause-stop-hide",
        "2.2.3": "no-timing",
        "2.2.4": "interruptions",
        "2.2.5": "re-authenticating",
        "2.2.6": "timeouts",
        "2.3.1": "three-flashes-or-below-threshold",
        "2.3.2": "three-flashes",
        "2.3.3": "animation-from-interactions",
        "2.4.1": "bypass-blocks",
        "2.4.2": "page-titled",
        "2.4.3": "focus-order",
        "2.4.4": "link-purpose-in-context",
        "2.4.5": "multiple-ways",
        "2.4.6": "headings-and-labels",
        "2.4.7": "focus-visible",
        "2.4.8": "location",
        "2.4.9": "link-purpose-link-only",
        "2.4.10": "section-headings",
        "2.4.11": "focus-not-obscured-minimum",
        "2.4.12": "focus-not-obscured-enhanced",
        "2.4.13": "focus-appearance",
        "2.5.1": "pointer-gestures",
        "2.5.2": "pointer-cancellation",
        "2.5.3": "label-in-name",
        "2.5.4": "motion-actuation",
        "2.5.5": "target-size-enhanced",
        "2.5.6": "concurrent-input-mechanisms",
        "2.5.7": "dragging-movements",
        "2.5.8": "target-size-minimum",
        "3.1.1": "language-of-page",
        "3.1.2": "language-of-parts",
        "3.1.3": "unusual-words",
        "3.1.4": "abbreviations",
        "3.1.5": "reading-level",
        "3.1.6": "pronunciation",
        "3.2.1": "on-focus",
        "3.2.2": "on-input",
        "3.2.3": "consistent-navigation",
        "3.2.4": "consistent-identification",
        "3.2.5": "change-on-request",
        "3.2.6": "consistent-help",
        "3.3.1": "error-identification",
        "3.3.2": "labels-or-instructions",
        "3.3.3": "error-suggestion",
        "3.3.4": "error-prevention-legal-financial-data",
        "3.3.5": "help",
        "3.3.6": "error-prevention-all",
        "3.3.7": "redundant-entry",
        "3.3.8": "accessible-authentication-minimum",
        "3.3.9": "accessible-authentication-enhanced",
        "4.1.1": "parsing",
        "4.1.2": "name-role-value",
        "4.1.3": "status-messages",
    }
    
    slug = slugs.get(criterion_id, criterion_id.replace(".", "-"))
    return f"https://www.w3.org/WAI/WCAG22/Understanding/{slug}"


def get_code_locations(rule_id: str) -> List[str]:
    """Find code locations where a rule is checked."""
    locations = []
    
    # Check rules_engine.py
    rules_engine = Path('backend/rules_engine.py')
    if rules_engine.exists():
        content = rules_engine.read_text(encoding='utf-8')
        if rule_id in content:
            locations.append("backend/rules_engine.py")
    
    # Check automated_checks.py
    auto_checks = Path('backend/automated_checks.py')
    if auto_checks.exists():
        content = auto_checks.read_text(encoding='utf-8')
        if rule_id in content:
            locations.append("backend/automated_checks.py")
    
    # Check advanced_checks.py
    adv_checks = Path('backend/advanced_checks.py')
    if adv_checks.exists():
        content = adv_checks.read_text(encoding='utf-8')
        if rule_id in content:
            locations.append("backend/advanced_checks.py")
    
    # Check playwright_analyzer.py
    pw_analyzer = Path('backend/playwright_analyzer.py')
    if pw_analyzer.exists():
        content = pw_analyzer.read_text(encoding='utf-8')
        if rule_id in content:
            locations.append("backend/playwright_analyzer.py")
    
    # Check pdf_accessibility.py
    pdf_acc = Path('backend/pdf_accessibility.py')
    if pdf_acc.exists():
        content = pdf_acc.read_text(encoding='utf-8')
        if rule_id in content:
            locations.append("backend/pdf_accessibility.py")
    
    # Check parsers
    for parser_file in Path('backend/parsers').glob('*.py'):
        content = parser_file.read_text(encoding='utf-8')
        if rule_id in content:
            locations.append(f"backend/parsers/{parser_file.name}")
    
    # Check rules files
    for rule_file in Path('rules').glob('*.jsonc'):
        content = rule_file.read_text(encoding='utf-8')
        if f'"{rule_id}"' in content:
            locations.append(f"rules/{rule_file.name}")
    
    return locations if locations else ["rules/*.jsonc (rule definition)"]


# Check types that ARE now implemented (browser-based)
IMPLEMENTED_BROWSER_CHECKS = {
    'contrast', 'non_text_contrast', 'target_size',
    'focus_appearance', 'focus_visible', 'label_in_name'
}

# Check types that ARE implemented (static analysis)
IMPLEMENTED_STATIC_CHECKS = {
    'link_text_quality', 'link_text_standalone', 'duplicate_id'
}

# All implemented check types
ALL_IMPLEMENTED_CHECK_TYPES = IMPLEMENTED_BROWSER_CHECKS | IMPLEMENTED_STATIC_CHECKS


def is_actually_automatable(rule: Dict) -> tuple:
    """
    Check if a rule is ACTUALLY automatable (not just claimed).
    Returns (is_automatable, reason)
    """
    if not rule.get('automatable', False):
        return False, "Manual review required"
    
    # Check each selector_check
    for check in rule.get('selector_checks', []):
        check_type = check.get('check_type', '')
        
        if check_type:
            if check_type in IMPLEMENTED_BROWSER_CHECKS:
                return True, f"Browser-based check ({check_type})"
            elif check_type in IMPLEMENTED_STATIC_CHECKS:
                return True, f"Static analysis check ({check_type})"
            else:
                return False, f"check_type '{check_type}' not implemented"
    
    # Standard CSS selector checks
    return True, "CSS selector checks implemented"


def generate_pdf_report():
    """Generate the PDF report."""
    
    # Collect all rules
    rules_dir = Path('rules')
    all_rules = []
    
    principle_names = {
        "1": "Perceivable",
        "2": "Operable", 
        "3": "Understandable",
        "4": "Robust"
    }
    
    for rule_file in sorted(rules_dir.glob('*.jsonc')):
        rules = load_rules_from_jsonc(rule_file)
        for rule in rules:
            rule['source_file'] = rule_file.name
            principle_num = rule.get('id', '0')[0]
            rule['principle'] = principle_names.get(principle_num, 'Unknown')
            all_rules.append(rule)
    
    # Sort by ID
    all_rules.sort(key=lambda r: [int(x) for x in r.get('id', '0.0.0').split('.')])
    
    # Create PDF
    output_path = Path('output/WCAG_Rules_Implementation_Report.pdf')
    output_path.parent.mkdir(exist_ok=True)
    
    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        rightMargin=0.5*inch,
        leftMargin=0.5*inch,
        topMargin=0.75*inch,
        bottomMargin=0.75*inch
    )
    
    # Styles
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        spaceAfter=30,
        alignment=TA_CENTER,
        textColor=colors.HexColor('#0891b2')
    )
    heading_style = ParagraphStyle(
        'CustomHeading',
        parent=styles['Heading2'],
        fontSize=16,
        spaceBefore=20,
        spaceAfter=10,
        textColor=colors.HexColor('#0891b2')
    )
    subheading_style = ParagraphStyle(
        'SubHeading',
        parent=styles['Heading3'],
        fontSize=12,
        spaceBefore=15,
        spaceAfter=8,
        textColor=colors.HexColor('#333333')
    )
    normal_style = ParagraphStyle(
        'CustomNormal',
        parent=styles['Normal'],
        fontSize=9,
        spaceAfter=6
    )
    small_style = ParagraphStyle(
        'Small',
        parent=styles['Normal'],
        fontSize=8,
        textColor=colors.HexColor('#666666')
    )
    
    # Build content
    story = []
    
    # Title
    story.append(Paragraph("WCAG 2.2 Rules Implementation Report", title_style))
    story.append(Paragraph(f"Generated: {datetime.now().strftime('%B %d, %Y at %H:%M')}", small_style))
    story.append(Paragraph(f"Total Rules Implemented: {len(all_rules)}", normal_style))
    story.append(Spacer(1, 20))
    
    # Summary table
    summary_data = [
        ['Principle', 'Rules Count', 'Level A', 'Level AA', 'Level AAA']
    ]
    
    for principle in ['Perceivable', 'Operable', 'Understandable', 'Robust']:
        p_rules = [r for r in all_rules if r.get('principle') == principle]
        level_a = len([r for r in p_rules if r.get('wcag_level') == 'A'])
        level_aa = len([r for r in p_rules if r.get('wcag_level') == 'AA'])
        level_aaa = len([r for r in p_rules if r.get('wcag_level') == 'AAA'])
        summary_data.append([principle, str(len(p_rules)), str(level_a), str(level_aa), str(level_aaa)])
    
    # Add totals
    total_a = len([r for r in all_rules if r.get('wcag_level') == 'A'])
    total_aa = len([r for r in all_rules if r.get('wcag_level') == 'AA'])
    total_aaa = len([r for r in all_rules if r.get('wcag_level') == 'AAA'])
    summary_data.append(['TOTAL', str(len(all_rules)), str(total_a), str(total_aa), str(total_aaa)])
    
    summary_table = Table(summary_data, colWidths=[1.8*inch, 1*inch, 0.8*inch, 0.8*inch, 0.8*inch])
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0891b2')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#e0f2fe')),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#cccccc')),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
        ('TOPPADDING', (0, 1), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 6),
    ]))
    
    story.append(Paragraph("Summary by WCAG Principle", heading_style))
    story.append(summary_table)
    story.append(Spacer(1, 30))
    
    # Detailed rules by principle
    for principle in ['Perceivable', 'Operable', 'Understandable', 'Robust']:
        story.append(PageBreak())
        story.append(Paragraph(f"{principle} Rules", heading_style))
        
        p_rules = [r for r in all_rules if r.get('principle') == principle]
        
        for rule in p_rules:
            rule_id = rule.get('id', 'N/A')
            rule_name = rule.get('name', 'Unknown')
            level = rule.get('wcag_level', 'N/A')
            description = rule.get('description', 'No description')
            
            # Check if ACTUALLY automatable
            actually_auto, auto_reason = is_actually_automatable(rule)
            if actually_auto:
                automatable = '✓ Yes'
            elif rule.get('automatable', False):
                automatable = f'⚠ Defined but not implemented ({auto_reason})'
            else:
                automatable = '✗ No'
            
            source = rule.get('source_file', 'Unknown')
            
            # Rule header
            story.append(Paragraph(
                f"<b>{rule_id}</b> - {rule_name} <font color='#0891b2'>[Level {level}]</font>",
                subheading_style
            ))
            
            # Description
            story.append(Paragraph(f"<i>{description}</i>", normal_style))
            
            # Details table
            wcag_url = get_wcag_url(rule_id)
            code_locs = get_code_locations(rule_id)
            
            details = [
                ['WCAG Reference:', f'<link href="{wcag_url}">{wcag_url}</link>'],
                ['Automatable:', automatable],
                ['Rule Definition:', source],
                ['Code Locations:', ', '.join(code_locs)]
            ]
            
            for label, value in details:
                story.append(Paragraph(f"<b>{label}</b> {value}", small_style))
            
            # Selector checks if any
            if rule.get('selector_checks'):
                story.append(Paragraph("<b>Automated Checks:</b>", small_style))
                for check in rule.get('selector_checks', [])[:3]:  # Limit to 3
                    selector = check.get('selector', 'N/A')[:60]
                    error = check.get('error', 'N/A')[:60]
                    story.append(Paragraph(f"  • Selector: <font face='Courier' size='7'>{selector}</font>", small_style))
                    story.append(Paragraph(f"    Error: {error}", small_style))
            
            story.append(Spacer(1, 10))
    
    # Browser-based checks section
    story.append(PageBreak())
    story.append(Paragraph("Browser-Based Automated Checks", heading_style))
    story.append(Paragraph(
        "These checks require browser rendering (Playwright) to compute styles and measure elements:",
        normal_style
    ))
    
    browser_checks = [
        ("contrast", "1.4.3, 1.4.6", "Text contrast ratio calculation", 
         "Computes actual foreground/background colors, calculates WCAG ratio (4.5:1 normal, 3:1 large text)"),
        ("non_text_contrast", "1.4.11", "UI component contrast",
         "Checks borders and visual boundaries of inputs, buttons against background (3:1 minimum)"),
        ("target_size", "2.5.5, 2.5.8", "Interactive element size",
         "Measures clickable areas - minimum 24x24px (AA) or 44x44px (AAA)"),
        ("focus_appearance", "2.4.7, 2.4.11", "Focus indicator visibility",
         "Programmatically focuses elements and checks for visible outline/box-shadow changes"),
        ("link_text_quality", "2.4.4, 2.4.9", "Link text descriptiveness",
         "NLP analysis detecting vague phrases ('click here', 'read more', etc.)"),
        ("label_in_name", "2.5.3", "Accessible name matching",
         "Compares visible label text against aria-label/aria-labelledby"),
        ("duplicate_id", "4.1.1", "Unique ID validation",
         "Scans for duplicate ID attributes in DOM"),
    ]
    
    browser_table_data = [['Check Type', 'WCAG', 'Purpose', 'How It Works']]
    for check in browser_checks:
        browser_table_data.append(list(check))
    
    browser_table = Table(browser_table_data, colWidths=[1.1*inch, 0.8*inch, 1.4*inch, 2.8*inch])
    browser_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#059669')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('FONTSIZE', (0, 1), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('TOPPADDING', (0, 1), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 4),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cccccc')),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))
    
    story.append(browser_table)
    story.append(Spacer(1, 15))
    story.append(Paragraph(
        "<b>Implementation:</b> backend/automated_checks.py, backend/advanced_checks.py, backend/playwright_analyzer.py",
        small_style
    ))
    
    # PDF-specific rules section
    story.append(PageBreak())
    story.append(Paragraph("PDF-Specific Accessibility Checks", heading_style))
    story.append(Paragraph(
        "In addition to the WCAG rules above, the platform includes deep PDF structure validation:",
        normal_style
    ))
    
    pdf_checks = [
        ("Document Metadata", "2.4.2, 3.1.1", "Title, language, bookmarks", "backend/pdf_accessibility.py"),
        ("Tagged Structure", "1.3.1", "Checks if PDF has structure tree", "backend/pdf_accessibility.py"),
        ("Heading Hierarchy", "1.3.1, 2.4.6", "Validates H1→H2→H3 order, detects skips", "backend/pdf_accessibility.py"),
        ("Visual Heading Detection", "1.3.1", "Finds large/bold text not tagged as heading", "backend/pdf_accessibility.py"),
        ("Table Structure", "1.3.1", "Validates Table/TH/TR/TD structure", "backend/pdf_accessibility.py"),
        ("List Structure", "1.3.1", "Validates L/LI/Lbl/LBody structure", "backend/pdf_accessibility.py"),
        ("Alt Text Quality", "1.1.1", "Checks for empty/placeholder alt text", "backend/pdf_accessibility.py"),
        ("Untagged URLs", "2.4.4", "Finds URLs in text not tagged as Link", "backend/pdf_accessibility.py"),
        ("Reading Order", "1.3.2", "Detects multi-column layout issues", "backend/pdf_accessibility.py"),
        ("Span Overuse", "1.3.1", "Detects poor tag structure", "backend/pdf_accessibility.py"),
        ("Scanned Content", "1.4.5", "Detects image-based pages", "backend/pdf_accessibility.py"),
        ("Form Labels", "3.3.2", "Checks form field accessibility", "backend/pdf_accessibility.py"),
    ]
    
    pdf_table_data = [['Check', 'WCAG Criteria', 'Description', 'Code Location']]
    for check in pdf_checks:
        pdf_table_data.append(list(check))
    
    pdf_table = Table(pdf_table_data, colWidths=[1.3*inch, 0.9*inch, 2.2*inch, 1.8*inch])
    pdf_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0891b2')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('FONTSIZE', (0, 1), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('TOPPADDING', (0, 1), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 4),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cccccc')),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))
    
    story.append(pdf_table)
    
    # Build PDF
    doc.build(story)
    print(f"\n✅ Report generated: {output_path.absolute()}")
    return output_path


if __name__ == "__main__":
    generate_pdf_report()

