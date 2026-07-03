# WCAG 2.2 Accessibility Remediation Platform

An automated accessibility audit engine for web pages and PDF documents based on the **Web Content Accessibility Guidelines (WCAG) 2.2** standard.

![WCAG 2.2](https://img.shields.io/badge/WCAG-2.2-blue)
![Python](https://img.shields.io/badge/Python-3.10+-green)
![React](https://img.shields.io/badge/React-18+-61dafb)
![FastAPI](https://img.shields.io/badge/FastAPI-0.109+-009688)

## Overview

This platform provides:

- **Automated Accessibility Audits** - Run documents against 80+ WCAG 2.2 success criteria
- **Selector-Based Checks** - CSS selector patterns to detect common accessibility issues
- **Contrast Analysis** - Compute color contrast ratios using Playwright browser automation
- **PDF Support** - Analyze tagged PDF structure and metadata
- **Automated Remediation** - Apply fixes for automatable issues
- **Visual Reports** - Interactive dashboard with filtering and export options

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     React Frontend                               │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────────┐ │
│  │  Upload  │  │Dashboard │  │Issue List│  │Remediation Panel │ │
│  └──────────┘  └──────────┘  └──────────┘  └──────────────────┘ │
└────────────────────────────────┬────────────────────────────────┘
                                 │ REST API
┌────────────────────────────────┼────────────────────────────────┐
│                     FastAPI Backend                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────────┐ │
│  │  /upload │  │ /analyze │  │/remediate│  │     /rules       │ │
│  └──────────┘  └──────────┘  └──────────┘  └──────────────────┘ │
│                          │                                       │
│              ┌───────────┴───────────┐                          │
│              │     Rules Engine      │                          │
│              │  (Selector Checks)    │                          │
│              └───────────┬───────────┘                          │
│                          │                                       │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────────┐ │
│  │HTML Parse│  │PDF Parser│  │Playwright│  │   Remediator     │ │
│  └──────────┘  └──────────┘  └──────────┘  └──────────────────┘ │
└────────────────────────────────┬────────────────────────────────┘
                                 │
┌────────────────────────────────┼────────────────────────────────┐
│                     WCAG Rule Files                              │
│  ┌────────────────┐  ┌────────────────┐  ┌────────────────────┐ │
│  │  Perceivable   │  │   Operable     │  │  Understandable    │ │
│  │  (JSONC)       │  │   (JSONC)      │  │     (JSONC)        │ │
│  └────────────────┘  └────────────────┘  └────────────────────┘ │
│                      ┌────────────────┐                         │
│                      │     Robust     │                         │
│                      │    (JSONC)     │                         │
│                      └────────────────┘                         │
└─────────────────────────────────────────────────────────────────┘
```

## WCAG Principles

The rules are organized by the four WCAG principles:

| Principle | Description | Rule Count |
|-----------|-------------|------------|
| **1. Perceivable** | Information must be presentable to users | 29 criteria |
| **2. Operable** | UI components must be operable | 29 criteria |
| **3. Understandable** | Information and UI must be understandable | 17 criteria |
| **4. Robust** | Content must work with assistive technologies | 3 criteria |

## Quick Start

### Prerequisites

- Python 3.10+
- Node.js 18+
- npm or yarn
- Java 11+ for OpenDataLoader PDF extraction

### Backend Setup

```bash
# Navigate to backend directory
cd backend

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# OpenDataLoader options
# Option 1: install the published wrapper (included in requirements.txt)
# Option 2: point to a local source checkout with:
#   OPENDATALOADER_ROOT=../opendataloader-pdf-main
# If you use the local checkout, build it first:
#   cd ../opendataloader-pdf-main/java && mvn package
#   cd ../python/opendataloader-pdf && pip install .

# Install Playwright browsers (for contrast/rendering checks)
playwright install chromium

# Start the server
uvicorn main:app --reload --port 8000
```

### Frontend Setup

```bash
# Navigate to frontend directory
cd frontend

# Install dependencies
npm install

# Start development server
npm run dev
```

The application will be available at:
- Frontend: http://localhost:5173
- Backend API: http://localhost:8000
- API Docs: http://localhost:8000/docs

## PDF Auto-Tagging

PDF auto-tagging now uses OpenDataLoader to extract layout structure as JSON,
then writes the PDF structure tree with the platform's existing `pikepdf`
writer. The `pdf` output mode from OpenDataLoader is not used for tagging.

Runtime resolution order:
- Built local checkout at `opendataloader-pdf-main`
- Installed `opendataloader-pdf==2.2.1`

If you use the local checkout, the extracted source tree must be built first
because it does not include a bundled CLI JAR by default.

## PDF Unicode Mapping Repair

The remediation pipeline scans actual PDF text-showing operators for character
codes that are missing from a font's `ToUnicode` map. Authoritative embedded
font metadata is used first and does not invoke an LLM.

Only ambiguous mappings are sent to `gemini-3.1-flash-lite`. The synchronous
vision request includes an
isolated glyph, representative line crops from distinct pages, masked nearby
text, typographic position, font metadata, and candidate Unicode values. Set
`GEMINI_API_KEY` to enable this fallback. Optional `GEMINI_MODEL` and
`GEMINI_API_ENDPOINT` variables override the model and Google's OpenAI-compatible
Chat Completions endpoint. The verifier fails closed when
multimodal input cannot be confirmed, when confidence is below `0.98`, when
occurrences conflict, or when a credible alternative remains.

Rejected decisions leave the PDF unchanged. Remediation results and generated
JSON and PDF reports separately disclose whether Gemini was invoked and whether its
recommendation was applied.

## API Endpoints

### Upload Document

```bash
POST /upload
Content-Type: multipart/form-data

# Upload HTML or PDF file for analysis
curl -X POST -F "file=@document.html" http://localhost:8000/upload
```

### Analyze Document

```bash
POST /analyze
Content-Type: application/json

{
  "file_id": "uuid-from-upload",
  "target_level": "AA",
  "include_aaa": false
}
```

### Analyze URL

```bash
GET /analyze/url?url=https://example.com&target_level=AA
```

### Apply Remediations

```bash
POST /remediate
Content-Type: application/json

{
  "report_id": "uuid-from-analyze",
  "apply_all_automatable": true
}
```

### List Rules

```bash
GET /rules?level=AA&tag=images&automatable=true
```

## Rule File Format

Rules are defined in JSONC format (JSON with comments):

```jsonc
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

## Detected Issues

The platform can detect issues including:

### Perceivable (WCAG 1.x)
- Missing alt text on images (1.1.1)
- Missing video captions (1.2.2)
- Missing form labels (1.3.1)
- Insufficient color contrast (1.4.3)
- Text resize restrictions (1.4.4)
- Reflow issues (1.4.10)

### Operable (WCAG 2.x)
- Keyboard accessibility (2.1.1)
- Keyboard traps (2.1.2)
- Missing skip links (2.4.1)
- Missing page titles (2.4.2)
- Focus order issues (2.4.3)
- Generic link text (2.4.4)
- Missing focus indicators (2.4.7)
- Target size issues (2.5.8)

### Understandable (WCAG 3.x)
- Missing language attribute (3.1.1)
- Missing error identification (3.3.1)
- Missing form labels (3.3.2)
- CAPTCHA accessibility (3.3.8)

### Robust (WCAG 4.x)
- Missing ARIA states (4.1.2)
- Missing status messages (4.1.3)

## Automated Fixes

The remediator can automatically fix:

- ✅ Add placeholder alt attributes
- ✅ Add missing page titles
- ✅ Add language attributes
- ✅ Add form labels
- ✅ Add ARIA labels
- ✅ Fix PDF metadata

> **Note:** Automated fixes add placeholder values that should be reviewed and customized.

## Running Tests

```bash
cd backend
pytest tests/ -v
```

## Project Structure

```
WCAG Project/
├── rules/                      # WCAG rule definitions
│   ├── wcag_perceivable.jsonc
│   ├── wcag_operable.jsonc
│   ├── wcag_understandable.jsonc
│   └── wcag_robust.jsonc
├── backend/                    # FastAPI backend
│   ├── main.py                 # API endpoints
│   ├── rules_engine.py         # Core analysis engine
│   ├── models.py               # Pydantic models
│   ├── config.py               # Configuration
│   ├── remediator.py           # Automated fixes
│   ├── playwright_analyzer.py  # Browser-based checks
│   ├── parsers/
│   │   ├── html_parser.py
│   │   └── pdf_parser.py
│   └── tests/
│       ├── test_rules_engine.py
│       ├── test_parsers.py
│       └── test_api.py
├── frontend/                   # React frontend
│   ├── src/
│   │   ├── App.tsx
│   │   ├── api.ts
│   │   ├── types.ts
│   │   └── components/
│   │       ├── Header.tsx
│   │       ├── UploadZone.tsx
│   │       ├── Dashboard.tsx
│   │       ├── IssueList.tsx
│   │       └── RemediationPanel.tsx
│   ├── package.json
│   └── tailwind.config.js
└── README.md
```

## Extending Rules

To add new WCAG criteria or custom rules:

1. Edit the appropriate JSONC file in `rules/`
2. Add a new rule object with:
   - `id`: WCAG criterion number
   - `name`: Criterion name
   - `wcag_level`: A, AA, or AAA
   - `selector_checks`: Array of CSS selector-based checks
   - `tags`: Categories for filtering

3. For complex checks, extend `rules_engine.py` with custom check types

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Submit a pull request

## License

MIT License - see LICENSE file for details.

## References

- [WCAG 2.2 Specification](https://www.w3.org/TR/WCAG22/)
- [Understanding WCAG 2.2](https://www.w3.org/WAI/WCAG22/Understanding/)
- [WCAG Quick Reference](https://www.w3.org/WAI/WCAG22/quickref/)
- [WAI-ARIA 1.2](https://www.w3.org/TR/wai-aria-1.2/)





