# WCAG 2.2 Accessibility Remediation Platform
## Technical Documentation

---

## 1. Overview

The **WCAG 2.2 Accessibility Remediation Platform** is an automated accessibility audit engine designed to analyze PDF documents and web pages against the Web Content Accessibility Guidelines (WCAG) 2.2 standard.

### Key Capabilities
- Upload and analyze PDF documents for accessibility compliance
- Detect WCAG violations with specific criterion references
- Apply automated fixes for certain issues (title, language, bookmarks)
- Generate detailed compliance reports
- Support for PDF/UA (ISO 14289-1) compliance checking

---

## 2. Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    FastAPI Backend                          │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐ │
│  │   /upload   │  │  /analyze   │  │    /remediate       │ │
│  └─────────────┘  └─────────────┘  └─────────────────────┘ │
│          │              │                    │              │
│          └──────────────┼────────────────────┘              │
│                         │                                   │
│              ┌──────────▼──────────┐                       │
│              │    Rules Engine     │                       │
│              │   (87 WCAG Rules)   │                       │
│              └──────────┬──────────┘                       │
│                         │                                   │
│  ┌──────────────────────┼──────────────────────┐           │
│  │                      │                      │           │
│  ▼                      ▼                      ▼           │
│ PDF Parser      PDF Accessibility      Remediator          │
│ (PyMuPDF)         Analyzer            (pikepdf)           │
└─────────────────────────────────────────────────────────────┘
                         │
                         ▼
              ┌─────────────────────┐
              │   WCAG Rule Files   │
              │      (JSONC)        │
              └─────────────────────┘
```

---

## 3. Module Descriptions

### 3.1 `backend/main.py` - FastAPI Application

The main application entry point that defines all REST API endpoints.

#### Key Endpoints:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/upload` | POST | Upload PDF/HTML files for analysis |
| `/analyze` | POST | Run general accessibility analysis |
| `/pdf/analyze` | POST | Detailed PDF-specific analysis |
| `/pdf/remediate` | POST | Apply automated fixes to PDF |
| `/pdf/download/{id}` | GET | Download processed PDF |
| `/rules` | GET | List all WCAG rules |
| `/health` | GET | Server health check |

#### Key Functions:

```python
async def upload_file(file: UploadFile)
    """
    Accepts file upload, validates type (PDF/HTML),
    stores file and returns unique file_id.
    """

async def analyze_pdf_document(file_id: str)
    """
    Runs comprehensive PDF accessibility analysis.
    Returns metadata, structure, compliance status, and issues.
    """

async def remediate_pdf_document(file_id, title, language, add_bookmarks)
    """
    Applies automated fixes to PDF metadata.
    Can set title, language, and generate bookmarks.
    """
```

---

### 3.2 `backend/pdf_accessibility.py` - PDF Analyzer

The core PDF accessibility analysis module that checks documents against WCAG 2.2 and PDF/UA requirements.

#### Classes:

**`PDFAccessibilityAnalyzer`**
```python
class PDFAccessibilityAnalyzer:
    """
    Comprehensive PDF accessibility analyzer.
    
    Methods:
    - analyze() -> Dict: Full accessibility analysis
    - _extract_metadata() -> PDFMetadata: Get document properties
    - _analyze_structure() -> PDFStructure: Parse tag structure
    - _check_title(): WCAG 2.4.2 - Page Titled
    - _check_language(): WCAG 3.1.1 - Language of Page
    - _check_tagged(): WCAG 1.3.1 - Info and Relationships
    - _check_alt_text(): WCAG 1.1.1 - Non-text Content
    - _check_reading_order(): WCAG 1.3.2 - Meaningful Sequence
    - _check_tables(): WCAG 1.3.1 - Table structure
    - _check_headings(): WCAG 2.4.6 - Headings and Labels
    - _check_bookmarks(): WCAG 2.4.5 - Multiple Ways
    - _check_links(): WCAG 2.4.4 - Link Purpose
    - _check_forms(): WCAG 3.3.2 - Labels or Instructions
    - _check_scanned_content(): WCAG 1.4.5 - Images of Text
    """
```

**`PDFRemediator`**
```python
class PDFRemediator:
    """
    Applies automated fixes to PDFs.
    
    Methods:
    - fix_metadata(title, language, author, subject)
        Sets document metadata properties.
        
    - generate_bookmarks_from_headings()
        Creates navigation bookmarks from heading structure.
    """
```

#### Data Classes:

```python
@dataclass
class PDFMetadata:
    title: Optional[str]
    author: Optional[str]
    language: Optional[str]
    page_count: int
    is_tagged: bool
    has_bookmarks: bool
    pdf_version: str
    file_size: int

@dataclass
class PDFStructure:
    has_structure_tree: bool
    tag_types: List[str]
    figure_count: int
    figures_with_alt: int
    table_count: int
    tables_with_headers: int
    heading_count: Dict[str, int]
    link_count: int

@dataclass
class PDFIssue:
    issue_type: PDFIssueType
    wcag_criterion: str
    wcag_name: str
    wcag_level: str  # A, AA, AAA
    severity: str    # error, warning, info
    message: str
    fix_suggestion: str
    page_number: Optional[int]
    auto_fixable: bool
```

---

### 3.3 `backend/rules_engine.py` - WCAG Rules Engine

The core engine that loads and executes WCAG rules from JSONC configuration files.

#### Class: `RulesEngine`

```python
class RulesEngine:
    """
    Core engine for executing WCAG accessibility checks.
    
    Attributes:
    - rules: Dict[str, List[WCAGRule]] - Rules by principle
    - rule_files: Dict[str, RuleFile] - Loaded rule files
    
    Methods:
    - get_all_rules() -> List[WCAGRule]
        Returns all 87 loaded WCAG rules.
        
    - get_rules_by_level(level: WCAGLevel) -> List[WCAGRule]
        Filter rules by conformance level (A, AA, AAA).
        
    - get_rule_by_id(rule_id: str) -> WCAGRule
        Get specific rule (e.g., "1.1.1").
        
    - get_automatable_rules() -> List[WCAGRule]
        Get rules that can be automatically checked.
        
    - analyze_html(html_content, doc_info, target_level)
        Run all applicable rules against HTML content.
    """
```

#### Class: `ColorUtils`

```python
class ColorUtils:
    """
    Utility class for color contrast calculations.
    WCAG 1.4.3 Contrast (Minimum)
    
    Methods:
    - hex_to_rgb(hex_color) -> Tuple[int, int, int]
    - rgb_to_relative_luminance(r, g, b) -> float
    - calculate_contrast_ratio(color1, color2) -> float
    - is_large_text(font_size, is_bold) -> bool
    """
```

---

### 3.4 `backend/parsers/pdf_parser.py` - PDF Parser

Low-level PDF parsing utilities using PyMuPDF and pikepdf.

```python
class PDFParser:
    """
    Parser for PDF documents with accessibility-focused extraction.
    
    Methods:
    - get_document_metadata() -> Dict
        Extract title, language, page count, tagged status.
        
    - check_tagged_structure() -> Dict
        Analyze PDF structure tree for tags.
        
    - extract_text_by_page() -> List[Dict]
        Get text content from each page.
        
    - extract_images() -> List[Dict]
        Get information about embedded images.
        
    - extract_links() -> List[Dict]
        Get hyperlinks from document.
        
    - check_reading_order() -> Dict
        Analyze reading order for multi-column layouts.
        
    - get_accessibility_summary() -> Dict
        Combined accessibility analysis.
    """
```

---

### 3.5 `rules/` - WCAG Rule Definitions

Four JSONC files containing all WCAG 2.2 success criteria:

| File | Principle | Rule Count |
|------|-----------|------------|
| `wcag_perceivable.jsonc` | 1. Perceivable | 29 rules |
| `wcag_operable.jsonc` | 2. Operable | 34 rules |
| `wcag_understandable.jsonc` | 3. Understandable | 21 rules |
| `wcag_robust.jsonc` | 4. Robust | 3 rules |

#### Rule Structure:

```json
{
  "id": "1.1.1",
  "name": "Non-text Content",
  "wcag_level": "A",
  "description": "All non-text content has a text alternative",
  "automatable": true,
  "automation_notes": "Can detect missing alt attributes",
  "selector_checks": [
    {
      "selector": "img:not([alt])",
      "error": "Image is missing alt attribute",
      "fix": "Add alt attribute describing the image"
    }
  ],
  "manual_review_required": true,
  "tags": ["images", "text-alternatives"]
}
```

---

## 4. PDF Accessibility Checks

### 4.1 Checks Performed

| Check | WCAG | Level | Auto-Fixable |
|-------|------|-------|--------------|
| Document Title | 2.4.2 | A | ✅ Yes |
| Document Language | 3.1.1 | A | ✅ Yes |
| Tagged PDF | 1.3.1 | A | ❌ No |
| Alt Text on Images | 1.1.1 | A | ❌ No |
| Reading Order | 1.3.2 | A | ❌ No |
| Table Headers | 1.3.1 | A | ❌ No |
| Heading Structure | 2.4.6 | AA | ❌ No |
| Bookmarks | 2.4.5 | AA | ✅ Yes |
| Link Tagging | 2.4.4 | A | ❌ No |
| Form Labels | 3.3.2 | A | ❌ No |
| Scanned Content | 1.4.5 | AA | ❌ No |

### 4.2 Analysis Output

```json
{
  "metadata": {
    "title": "Document Title",
    "language": "en",
    "page_count": 10,
    "is_tagged": true,
    "has_bookmarks": true
  },
  "structure": {
    "has_structure_tree": true,
    "figure_count": 5,
    "figures_with_alt": 3,
    "table_count": 2,
    "heading_count": {"H1": 1, "H2": 4}
  },
  "compliance": {
    "wcag_a_compliant": false,
    "wcag_aa_compliant": false,
    "pdf_ua_compliant": false
  },
  "summary": {
    "total_issues": 3,
    "errors": 2,
    "warnings": 1,
    "auto_fixable": 1
  },
  "issues": [...]
}
```

---

## 5. API Usage Examples

### 5.1 Upload a PDF

```powershell
# PowerShell
$response = Invoke-RestMethod -Uri "http://localhost:8000/upload" `
    -Method Post -Form @{ file = Get-Item "document.pdf" }
$fileId = $response.file_id
```

### 5.2 Analyze PDF

```powershell
$analysis = Invoke-RestMethod `
    -Uri "http://localhost:8000/pdf/analyze?file_id=$fileId" `
    -Method Post
```

### 5.3 Apply Fixes

```powershell
$result = Invoke-RestMethod `
    -Uri "http://localhost:8000/pdf/remediate?file_id=$fileId&title=My%20Doc&language=en" `
    -Method Post
```

### 5.4 Download Fixed PDF

```powershell
Invoke-WebRequest `
    -Uri "http://localhost:8000/pdf/download/$fileId" `
    -OutFile "fixed_document.pdf"
```

---

## 6. Dependencies

### Python Packages

| Package | Purpose |
|---------|---------|
| FastAPI | REST API framework |
| uvicorn | ASGI server |
| PyMuPDF (fitz) | PDF parsing and manipulation |
| pikepdf | PDF metadata editing |
| beautifulsoup4 | HTML parsing |
| pydantic | Data validation |
| aiofiles | Async file operations |

### Installation

```bash
pip install fastapi uvicorn PyMuPDF pikepdf beautifulsoup4 pydantic aiofiles
```

---

## 7. File Structure

```
WCAG Project/
├── backend/
│   ├── main.py                 # FastAPI application
│   ├── pdf_accessibility.py    # PDF analyzer & remediator
│   ├── rules_engine.py         # WCAG rules engine
│   ├── models.py               # Pydantic data models
│   ├── config.py               # Configuration
│   ├── parsers/
│   │   ├── html_parser.py      # HTML parsing utilities
│   │   └── pdf_parser.py       # PDF parsing utilities
│   └── tests/                  # Unit tests
├── rules/
│   ├── wcag_perceivable.jsonc  # Principle 1 rules
│   ├── wcag_operable.jsonc     # Principle 2 rules
│   ├── wcag_understandable.jsonc # Principle 3 rules
│   └── wcag_robust.jsonc       # Principle 4 rules
├── uploads/                    # Uploaded files
├── output/                     # Processed files
└── run_backend.py              # Server startup script
```

---

## 8. Running the Application

```bash
# Start the server
python run_backend.py

# Server runs at:
# - API: http://localhost:8000
# - Docs: http://localhost:8000/docs
# - Health: http://localhost:8000/health
```

---

## 9. Future Enhancements

- [ ] OCR integration for scanned PDFs
- [ ] AI-powered alt text generation
- [ ] Batch processing of multiple PDFs
- [ ] Detailed remediation reports
- [ ] Integration with Adobe Acrobat API
- [ ] React frontend dashboard

---

*Document generated for WCAG 2.2 Accessibility Remediation Platform*
*Version 1.0.0*





