"""
PDF Accessibility Analyzer and Remediator.

Specialized module for PDF/UA compliance checking and remediation.
Based on WCAG 2.2 and PDF/UA (ISO 14289-1) standards.

Key PDF Accessibility Requirements:
- Document must be tagged (WCAG 1.3.1)
- Must have document title (WCAG 2.4.2)
- Must specify language (WCAG 3.1.1)
- Images must have alt text (WCAG 1.1.1)
- Reading order must be logical (WCAG 1.3.2)
- Tables must have headers (WCAG 1.3.1)
- Links must be identifiable (WCAG 2.4.4)
- Text must be real text, not images (WCAG 1.4.5)
"""
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


def normalize_language_code(lang: Optional[str]) -> str:
    """Normalize language name/code to standard ISO 639-1 or BCP 47 format."""
    if not lang:
        return "en"
    
    lang = lang.strip().lower()
    
    # Common language name to code mapping
    name_to_code = {
        "english": "en",
        "french": "fr",
        "spanish": "es",
        "german": "de",
        "portuguese": "pt",
        "italian": "it",
        "chinese": "zh",
        "japanese": "ja",
        "russian": "ru",
        "arabic": "ar",
        "hindi": "hi",
        "nepali": "ne",
        "khmer": "km",
        "burmese": "my",
        "korean": "ko",
        "dutch": "nl",
        "swedish": "sv",
        "polish": "pl",
        "turkish": "tr"
    }
    
    if lang in name_to_code:
        return name_to_code[lang]
    
    import re
    
    # Standardize separator to hyphen for BCP 47 (e.g. en_US -> en-US)
    lang = lang.replace("_", "-")
    
    # Check if it matches ISO 639-1 (2 letters), ISO 639-2 (3 letters), or BCP 47
    if re.match(r"^[a-z]{2,3}(-[a-z0-9]+)*$", lang):
        return lang
        
    return "en"


try:
    import fitz  # PyMuPDF
    HAS_PYMUPDF = True
except ImportError:
    HAS_PYMUPDF = False
    logger.warning("PyMuPDF not installed - PDF analysis limited")

try:
    import pikepdf
    HAS_PIKEPDF = True
except ImportError:
    HAS_PIKEPDF = False
    logger.warning("pikepdf not installed - PDF metadata editing limited")


class PDFIssueType(Enum):
    """Types of PDF accessibility issues."""
    MISSING_TITLE = "missing_title"
    MISSING_LANGUAGE = "missing_language"
    NOT_TAGGED = "not_tagged"
    MISSING_ALT_TEXT = "missing_alt_text"
    EMPTY_ALT_TEXT = "empty_alt_text"
    MISSING_TABLE_HEADERS = "missing_table_headers"
    TABLE_STRUCTURE_INVALID = "table_structure_invalid"
    READING_ORDER = "reading_order"
    MISSING_BOOKMARKS = "missing_bookmarks"
    SCANNED_IMAGE = "scanned_image"
    FORM_FIELDS_UNLABELED = "form_fields_unlabeled"
    COLOR_ONLY = "color_only"
    LOW_CONTRAST = "low_contrast"
    LINK_NOT_TAGGED = "link_not_tagged"
    UNTAGGED_URL = "untagged_url"
    HEADING_HIERARCHY = "heading_hierarchy"
    VISUAL_HEADING_NOT_TAGGED = "visual_heading_not_tagged"
    LIST_STRUCTURE_INVALID = "list_structure_invalid"
    SPAN_OVERUSE = "span_overuse"
    WRONG_TAG_TYPE = "wrong_tag_type"
    TAB_ORDER_NOT_STRUCTURE = "tab_order_not_structure"


@dataclass
class PDFIssue:
    """A PDF accessibility issue."""
    issue_type: PDFIssueType
    wcag_criterion: str
    wcag_name: str
    wcag_level: str
    severity: str  # error, warning, info
    message: str
    fix_suggestion: str
    page_number: Optional[int] = None
    element_info: Optional[Dict[str, Any]] = None
    auto_fixable: bool = False


@dataclass
class PDFMetadata:
    """PDF document metadata."""
    title: Optional[str] = None
    author: Optional[str] = None
    subject: Optional[str] = None
    keywords: Optional[str] = None
    creator: Optional[str] = None
    producer: Optional[str] = None
    language: Optional[str] = None
    page_count: int = 0
    is_tagged: bool = False
    has_bookmarks: bool = False
    pdf_version: Optional[str] = None
    is_encrypted: bool = False
    file_size: int = 0


@dataclass
class PDFStructure:
    """PDF structure analysis results."""
    has_structure_tree: bool = False
    tag_types: List[str] = None
    heading_count: Dict[str, int] = None
    heading_sequence: List[str] = None  # Track heading order for hierarchy validation
    figure_count: int = 0
    figures_with_alt: int = 0
    figures_with_empty_alt: int = 0  # Alt text exists but empty/placeholder
    table_count: int = 0
    tables_with_headers: int = 0
    tables_without_structure: int = 0  # Tables missing TR/TD structure
    link_count: int = 0
    untagged_urls: int = 0  # URLs in text not tagged as Link
    list_count: int = 0
    lists_without_structure: int = 0  # Lists missing L/LI structure
    form_field_count: int = 0
    form_fields_labeled: int = 0
    span_overuse: int = 0  # Excessive Span tags that should be P/H/etc
    paragraphs_as_headings: int = 0  # Visual headings tagged as P
    wrong_tag_types: List[Dict[str, Any]] = None  # Specific mismatches found
    tabs_not_s_count: int = 0  # Pages with annotations but /Tabs != /S
    
    def __post_init__(self):
        if self.heading_sequence is None:
            self.heading_sequence = []
        if self.wrong_tag_types is None:
            self.wrong_tag_types = []
        if self.tag_types is None:
            self.tag_types = []
        if self.heading_count is None:
            self.heading_count = {}


class PDFAccessibilityAnalyzer:
    """
    Comprehensive PDF accessibility analyzer.
    
    Checks PDFs against WCAG 2.2 and PDF/UA requirements.
    """
    
    def __init__(self, file_path: Optional[Path] = None, file_bytes: Optional[bytes] = None):
        """Initialize with PDF file."""
        self.file_path = file_path
        self.file_bytes = file_bytes
        self._fitz_doc = None
        self._pike_doc = None
        self.metadata: Optional[PDFMetadata] = None
        self.structure: Optional[PDFStructure] = None
        self.issues: List[PDFIssue] = []
    
    def _open_fitz(self):
        """Open document with PyMuPDF."""
        if self._fitz_doc is None and HAS_PYMUPDF:
            if self.file_path:
                self._fitz_doc = fitz.open(str(self.file_path))
            elif self.file_bytes:
                self._fitz_doc = fitz.open(stream=self.file_bytes, filetype="pdf")
        return self._fitz_doc
    
    def _open_pike(self):
        """Open document with pikepdf."""
        if self._pike_doc is None and HAS_PIKEPDF:
            if self.file_path:
                self._pike_doc = pikepdf.open(str(self.file_path))
            elif self.file_bytes:
                from io import BytesIO
                self._pike_doc = pikepdf.open(BytesIO(self.file_bytes))
        return self._pike_doc
    
    def close(self):
        """Close document handles."""
        if self._fitz_doc:
            self._fitz_doc.close()
            self._fitz_doc = None
        if self._pike_doc:
            self._pike_doc.close()
            self._pike_doc = None
    
    def analyze(self) -> Dict[str, Any]:
        """
        Perform full accessibility analysis.
        
        Returns comprehensive report with issues and recommendations.
        """
        self.issues = []
        
        # Extract metadata
        self.metadata = self._extract_metadata()
        
        # Analyze structure
        self.structure = self._analyze_structure()
        
        # Check all accessibility requirements
        self._check_title()           # WCAG 2.4.2
        self._check_language()        # WCAG 3.1.1
        self._check_tagged()          # WCAG 1.3.1
        self._check_alt_text()        # WCAG 1.1.1
        self._check_alt_text_quality()  # WCAG 1.1.1 - quality check
        self._check_reading_order()   # WCAG 1.3.2
        self._check_tables()          # WCAG 1.3.1
        self._check_headings()        # WCAG 1.3.1, 2.4.6 (now includes hierarchy validation)
        self._check_bookmarks()       # WCAG 2.4.5
        self._check_links()           # WCAG 2.4.4 (now includes untagged URL detection)
        self._check_list_structure()  # WCAG 1.3.1 - list validation
        self._check_span_overuse()    # WCAG 1.3.1 - tag quality
        self._check_forms()           # WCAG 1.3.1, 3.3.2
        self._check_scanned_content() # WCAG 1.4.5
        self._check_tab_order()        # PDF/UA + WCAG 2.4.3
        
        return self._generate_report()
    
    def _extract_metadata(self) -> PDFMetadata:
        """Extract PDF metadata."""
        metadata = PDFMetadata()
        
        # Get file size
        if self.file_path:
            metadata.file_size = self.file_path.stat().st_size
        elif self.file_bytes:
            metadata.file_size = len(self.file_bytes)
        
        # PyMuPDF metadata
        doc = self._open_fitz()
        if doc:
            metadata.page_count = len(doc)
            metadata.is_encrypted = doc.is_encrypted
            
            info = doc.metadata or {}
            metadata.title = info.get("title") or None
            metadata.author = info.get("author") or None
            metadata.subject = info.get("subject") or None
            metadata.keywords = info.get("keywords") or None
            metadata.creator = info.get("creator") or None
            metadata.producer = info.get("producer") or None
            
            # Check for bookmarks
            metadata.has_bookmarks = len(doc.get_toc()) > 0
            
            # Check if tagged
            try:
                catalog = doc.pdf_catalog()
                if catalog:
                    mark_info = doc.xref_get_key(catalog, "MarkInfo")
                    if mark_info and mark_info[0] != 'null':
                        metadata.is_tagged = True
            except Exception:
                pass
        
        # pikepdf for language and version
        pike = self._open_pike()
        if pike:
            metadata.pdf_version = str(pike.pdf_version)
            
            try:
                if '/Lang' in pike.Root:
                    metadata.language = str(pike.Root.Lang)
            except Exception:
                pass
        
        return metadata
    
    def _analyze_structure(self) -> PDFStructure:
        """Analyze PDF structure tree."""
        structure = PDFStructure()
        
        pike = self._open_pike()
        if not pike:
            return structure
        
        try:
            if '/StructTreeRoot' in pike.Root:
                structure.has_structure_tree = True
                struct_root = pike.Root.StructTreeRoot
                self._walk_structure_tree(struct_root, structure)
        except Exception as e:
            logger.debug(f"Error analyzing structure: {e}")
        
        return structure
    
    def _walk_structure_tree(self, element, structure: PDFStructure, depth: int = 0):
        """Recursively walk the structure tree."""
        if depth > 50:  # Prevent infinite recursion
            return
        
        try:
            if '/K' in element:
                kids = element.K
                if not isinstance(kids, list):
                    kids = [kids]
                
                for kid in kids:
                    if hasattr(kid, 'keys') and '/S' in kid:
                        tag_type = str(kid.S).strip('/')
                        
                        if tag_type not in structure.tag_types:
                            structure.tag_types.append(tag_type)
                        
                        if tag_type == 'Figure':
                            # Check if the figure covers the entire page
                            is_full_page = False
                            try:
                                page_obj = kid.get("/Pg")
                                if page_obj:
                                    pike = self._open_pike()
                                    page_idx = pike.pages.index(page_obj)
                                    fitz_doc = self._open_fitz()
                                    if fitz_doc and page_idx < len(fitz_doc):
                                        page = fitz_doc[page_idx]
                                        bbox = None
                                        if '/A' in kid:
                                            attr = kid.A
                                            if hasattr(attr, 'keys') and '/BBox' in attr:
                                                bbox = [float(x) for x in attr.BBox]
                                        if bbox:
                                            width_ratio = (bbox[2] - bbox[0]) / page.rect.width
                                            height_ratio = (bbox[3] - bbox[1]) / page.rect.height
                                            if width_ratio > 0.95 and height_ratio > 0.95:
                                                is_full_page = True
                            except Exception:
                                pass
                            
                            if not is_full_page:
                                structure.figure_count += 1
                                if '/Alt' in kid:
                                    alt_text = str(kid.Alt).strip()
                                    if alt_text and alt_text not in ['', 'image', 'figure', 'Image', 'Figure', 'img']:
                                        structure.figures_with_alt += 1
                                    else:
                                        structure.figures_with_empty_alt += 1
                        
                        elif tag_type == 'Table':
                            structure.table_count += 1
                            # Check for TH (table header) children
                            if self._has_table_headers(kid):
                                structure.tables_with_headers += 1
                        
                        elif tag_type in ['H1', 'H2', 'H3', 'H4', 'H5', 'H6', 'H']:
                            structure.heading_count[tag_type] = structure.heading_count.get(tag_type, 0) + 1
                            structure.heading_sequence.append(tag_type)
                        
                        elif tag_type == 'L':  # List
                            structure.list_count += 1
                            # Check for proper LI children
                            if not self._has_list_items(kid):
                                structure.lists_without_structure += 1
                        
                        elif tag_type == 'Span':
                            # Track span usage - too many spans might indicate poor tagging
                            structure.span_overuse += 1
                        
                        elif tag_type == 'Link':
                            structure.link_count += 1
                        
                        elif tag_type == 'Form':
                            structure.form_field_count += 1
                        
                        # Recurse
                        self._walk_structure_tree(kid, structure, depth + 1)
        except Exception:
            pass
    
    def _has_table_headers(self, table_element) -> bool:
        """Check if table has TH elements."""
        try:
            if '/K' in table_element:
                kids = table_element.K
                if not isinstance(kids, list):
                    kids = [kids]
                for kid in kids:
                    if hasattr(kid, 'keys') and '/S' in kid:
                        if str(kid.S) == '/TH':
                            return True
                        if self._has_table_headers(kid):
                            return True
        except Exception:
            pass
        return False
    
    def _has_list_items(self, list_element) -> bool:
        """Check if list has LI (list item) elements."""
        try:
            if '/K' in list_element:
                kids = list_element.K
                if not isinstance(kids, list):
                    kids = [kids]
                for kid in kids:
                    if hasattr(kid, 'keys') and '/S' in kid:
                        if str(kid.S) in ['/LI', '/Lbl', '/LBody']:
                            return True
        except Exception:
            pass
        return False
    
    def _check_title(self):
        """
        Check for document title.
        WCAG 2.4.2 Page Titled (Level A)
        """
        if not self.metadata.title:
            self.issues.append(PDFIssue(
                issue_type=PDFIssueType.MISSING_TITLE,
                wcag_criterion="2.4.2",
                wcag_name="Page Titled",
                wcag_level="A",
                severity="error",
                message="PDF document is missing a title",
                fix_suggestion="Add a descriptive title in the document properties (File > Properties > Description > Title)",
                auto_fixable=True
            ))
    
    def _check_language(self):
        """
        Check for document language.
        WCAG 3.1.1 Language of Page (Level A)
        """
        if not self.metadata.language:
            self.issues.append(PDFIssue(
                issue_type=PDFIssueType.MISSING_LANGUAGE,
                wcag_criterion="3.1.1",
                wcag_name="Language of Page",
                wcag_level="A",
                severity="error",
                message="PDF document does not specify a language",
                fix_suggestion="Set the document language in Advanced properties (File > Properties > Advanced > Language)",
                auto_fixable=True
            ))
    
    def _check_tagged(self):
        """
        Check if PDF is tagged.
        WCAG 1.3.1 Info and Relationships (Level A)
        PDF/UA Requirement
        """
        if not self.metadata.is_tagged:
            self.issues.append(PDFIssue(
                issue_type=PDFIssueType.NOT_TAGGED,
                wcag_criterion="1.3.1",
                wcag_name="Info and Relationships",
                wcag_level="A",
                severity="error",
                message="PDF is not tagged - screen readers cannot determine document structure",
                fix_suggestion="Use Adobe Acrobat's 'Add Tags to Document' feature or recreate from source with tagging enabled",
                auto_fixable=True
            ))
    
    def _check_alt_text(self):
        """
        Check for alternative text on images.
        WCAG 1.1.1 Non-text Content (Level A)
        """
        if self.structure.figure_count > 0:
            missing = self.structure.figure_count - self.structure.figures_with_alt
            if missing > 0:
                self.issues.append(PDFIssue(
                    issue_type=PDFIssueType.MISSING_ALT_TEXT,
                    wcag_criterion="1.1.1",
                    wcag_name="Non-text Content",
                    wcag_level="A",
                    severity="error",
                    message=f"{missing} image(s) missing alternative text",
                    fix_suggestion="Add alt text to each Figure in the Tags panel (right-click > Properties > Alternate Text)",
                    element_info={"total_figures": self.structure.figure_count, "missing_alt": missing},
                    auto_fixable=False
                ))
    
    def _check_reading_order(self):
        """
        Check reading order.
        WCAG 1.3.2 Meaningful Sequence (Level A)
        """
        doc = self._open_fitz()
        if not doc:
            return
        
        # Check for potential reading order issues
        for page_num, page in enumerate(doc):
            blocks = page.get_text("dict")["blocks"]
            
            if len(blocks) > 1:
                # Check for multi-column layout
                x_positions = [b["bbox"][0] for b in blocks if "bbox" in b]
                if x_positions:
                    x_range = max(x_positions) - min(x_positions)
                    if x_range > page.rect.width * 0.3:
                        self.issues.append(PDFIssue(
                            issue_type=PDFIssueType.READING_ORDER,
                            wcag_criterion="1.3.2",
                            wcag_name="Meaningful Sequence",
                            wcag_level="A",
                            severity="warning",
                            message=f"Page {page_num + 1} appears to have multi-column layout - verify reading order",
                            fix_suggestion="Check reading order in the Order panel and adjust if necessary",
                            page_number=page_num + 1,
                            auto_fixable=True
                        ))
                        break  # Only report once
    
    def _check_tables(self):
        """
        Check table structure.
        WCAG 1.3.1 Info and Relationships (Level A)
        """
        if self.structure.table_count > 0:
            missing = self.structure.table_count - self.structure.tables_with_headers
            if missing > 0:
                self.issues.append(PDFIssue(
                    issue_type=PDFIssueType.MISSING_TABLE_HEADERS,
                    wcag_criterion="1.3.1",
                    wcag_name="Info and Relationships",
                    wcag_level="A",
                    severity="error",
                    message=f"{missing} table(s) missing header cell markup",
                    fix_suggestion="Use the Table Editor to mark header cells with TH tags",
                    element_info={"total_tables": self.structure.table_count, "missing_headers": missing},
                    auto_fixable=True
                ))
    
    def _check_headings(self):
        """
        Check heading structure and hierarchy.
        WCAG 1.3.1 Info and Relationships (Level A)
        WCAG 2.4.6 Headings and Labels (Level AA)
        """
        # Check for missing headings
        if not self.structure.heading_count:
            if self.metadata.page_count > 1:
                self.issues.append(PDFIssue(
                    issue_type=PDFIssueType.NOT_TAGGED,
                    wcag_criterion="2.4.6",
                    wcag_name="Headings and Labels",
                    wcag_level="AA",
                    severity="warning",
                    message="Document has no tagged headings",
                    fix_suggestion="Add heading tags (H1, H2, etc.) to structure the document",
                    auto_fixable=True
                ))
            return
        
        # Check heading hierarchy
        hierarchy_issues = self._validate_heading_hierarchy()
        for issue in hierarchy_issues:
            self.issues.append(issue)
        
        # Check for visual headings not tagged as headings
        visual_heading_issues = self._check_visual_headings()
        for issue in visual_heading_issues:
            self.issues.append(issue)
    
    def _validate_heading_hierarchy(self) -> List[PDFIssue]:
        """
        Validate heading hierarchy - H2 should follow H1, no H1→H4 jumps.
        """
        issues = []
        sequence = self.structure.heading_sequence
        
        if not sequence:
            return issues
        
        # Check for missing H1
        if 'H1' not in self.structure.heading_count and sequence:
            issues.append(PDFIssue(
                issue_type=PDFIssueType.HEADING_HIERARCHY,
                wcag_criterion="1.3.1",
                wcag_name="Info and Relationships",
                wcag_level="A",
                severity="error",
                message="Document has headings but no H1 - document structure should start with H1",
                fix_suggestion="Add an H1 heading at the beginning of the document",
                auto_fixable=True
            ))
        
        # Check for hierarchy jumps (e.g., H1 → H4)
        prev_level = 0
        jump_count = 0
        for heading in sequence:
            if heading == 'H':
                continue  # Generic heading, skip
            try:
                level = int(heading[1])
                if prev_level > 0 and level > prev_level + 1:
                    jump_count += 1
                prev_level = level
            except (ValueError, IndexError):
                pass
        
        if jump_count > 0:
            issues.append(PDFIssue(
                issue_type=PDFIssueType.HEADING_HIERARCHY,
                wcag_criterion="1.3.1",
                wcag_name="Info and Relationships",
                wcag_level="A",
                severity="error",
                message=f"Heading hierarchy has {jump_count} skip(s) - headings should not skip levels (e.g., H1 to H4)",
                fix_suggestion="Fix heading levels to follow proper hierarchy (H1 → H2 → H3, not H1 → H4)",
                element_info={"jumps": jump_count, "sequence": sequence[:20]},
                auto_fixable=True
            ))
        
        return issues
    
    def _check_visual_headings(self) -> List[PDFIssue]:
        """
        Detect text that visually appears to be a heading but isn't tagged as one.
        Checks for large font sizes tagged as P/Span instead of H1-H6.
        """
        issues = []
        doc = self._open_fitz()
        if not doc:
            return issues
        
        potential_headings = 0
        try:
            for page_num in range(min(5, len(doc))):  # Check first 5 pages
                page = doc[page_num]
                blocks = page.get_text("dict")["blocks"]
                
                for block in blocks:
                    if "lines" not in block:
                        continue
                    for line in block["lines"]:
                        for span in line.get("spans", []):
                            font_size = span.get("size", 12)
                            text = span.get("text", "").strip()
                            
                            # Large text (>16pt) with short length might be a heading
                            if font_size >= 16 and len(text) > 0 and len(text) < 100:
                                # Check if it's bold
                                flags = span.get("flags", 0)
                                is_bold = flags & 2**4  # Bold flag
                                
                                if is_bold or font_size >= 20:
                                    potential_headings += 1
        except Exception as e:
            logger.debug(f"Error checking visual headings: {e}")
        
        # If we found potential headings but few tagged headings, flag it
        total_tagged = sum(self.structure.heading_count.values()) if self.structure.heading_count else 0
        if potential_headings > total_tagged * 2 and potential_headings > 3:
            issues.append(PDFIssue(
                issue_type=PDFIssueType.VISUAL_HEADING_NOT_TAGGED,
                wcag_criterion="1.3.1",
                wcag_name="Info and Relationships",
                wcag_level="A",
                severity="warning",
                message=f"Found ~{potential_headings} visual headings (large/bold text) but only {total_tagged} tagged headings",
                fix_suggestion="Review large/bold text and tag as appropriate heading level (H1-H6)",
                element_info={"visual_headings": potential_headings, "tagged_headings": total_tagged},
                auto_fixable=True
            ))
        
        return issues
    
    def _check_bookmarks(self):
        """
        Check for bookmarks/outline.
        WCAG 2.4.5 Multiple Ways (Level AA)
        """
        # Only flag for longer documents
        if self.metadata.page_count > 9 and not self.metadata.has_bookmarks:
            self.issues.append(PDFIssue(
                issue_type=PDFIssueType.MISSING_BOOKMARKS,
                wcag_criterion="2.4.5",
                wcag_name="Multiple Ways",
                wcag_level="AA",
                severity="warning",
                message="Document has no bookmarks for navigation",
                fix_suggestion="Add bookmarks based on heading structure for easier navigation",
                auto_fixable=True
            ))
    
    def _check_links(self):
        """
        Check link accessibility.
        WCAG 2.4.4 Link Purpose (Level A)
        """
        doc = self._open_fitz()
        if not doc:
            return
        
        untagged_links = 0
        for page in doc:
            links = page.get_links()
            for link in links:
                # Check if link is in structure tree
                if link.get("kind") == 2:  # URI link
                    untagged_links += 1
        
        if untagged_links > 0 and not self.structure.link_count:
            self.issues.append(PDFIssue(
                issue_type=PDFIssueType.LINK_NOT_TAGGED,
                wcag_criterion="2.4.4",
                wcag_name="Link Purpose (In Context)",
                wcag_level="A",
                severity="warning",
                message=f"{untagged_links} link(s) may not be properly tagged",
                fix_suggestion="Ensure all links have Link tags in the structure tree",
                auto_fixable=True
            ))
        
        # Check for URLs in text that aren't tagged as links
        self._check_untagged_urls()
    
    def _check_untagged_urls(self):
        """
        Detect URLs in text content that aren't tagged as Link elements.
        """
        import re
        doc = self._open_fitz()
        if not doc:
            return
        
        url_pattern = re.compile(r'https?://[^\s<>"{}|\\^`\[\]]+|www\.[^\s<>"{}|\\^`\[\]]+')
        untagged_urls = 0
        
        try:
            for page in doc:
                text = page.get_text("text")
                urls_in_text = url_pattern.findall(text)
                untagged_urls += len(urls_in_text)
        except Exception as e:
            logger.debug(f"Error checking untagged URLs: {e}")
        
        # Compare with tagged links
        if untagged_urls > self.structure.link_count:
            diff = untagged_urls - self.structure.link_count
            if diff > 0:
                self.issues.append(PDFIssue(
                    issue_type=PDFIssueType.UNTAGGED_URL,
                    wcag_criterion="2.4.4",
                    wcag_name="Link Purpose (In Context)",
                    wcag_level="A",
                    severity="error",
                    message=f"Found ~{untagged_urls} URLs in text but only {self.structure.link_count} tagged links - {diff} URL(s) may be untagged",
                    fix_suggestion="Tag all URLs as Link elements so screen readers can identify them as interactive",
                    element_info={"urls_in_text": untagged_urls, "tagged_links": self.structure.link_count},
                    auto_fixable=True
                ))
    
    def _check_list_structure(self):
        """
        Check list structure.
        WCAG 1.3.1 Info and Relationships (Level A)
        """
        if self.structure.lists_without_structure > 0:
            self.issues.append(PDFIssue(
                issue_type=PDFIssueType.LIST_STRUCTURE_INVALID,
                wcag_criterion="1.3.1",
                wcag_name="Info and Relationships",
                wcag_level="A",
                severity="error",
                message=f"{self.structure.lists_without_structure} list(s) missing proper structure (LI/Lbl/LBody tags)",
                fix_suggestion="Lists must use L (list), LI (list item), Lbl (label), and LBody (list body) tags",
                auto_fixable=True
            ))
    
    def _check_span_overuse(self):
        """
        Check for excessive Span tag usage which indicates poor structure.
        """
        # Calculate ratio of Span tags to total content tags
        total_content_tags = sum([
            self.structure.heading_count.get(h, 0) for h in ['H1', 'H2', 'H3', 'H4', 'H5', 'H6']
        ] if self.structure.heading_count else [0])
        total_content_tags += self.structure.figure_count
        total_content_tags += self.structure.table_count
        total_content_tags += self.structure.list_count
        
        # If Span count is very high compared to structural tags, flag it
        if self.structure.span_overuse > 50 and total_content_tags < 10:
            self.issues.append(PDFIssue(
                issue_type=PDFIssueType.SPAN_OVERUSE,
                wcag_criterion="1.3.1",
                wcag_name="Info and Relationships",
                wcag_level="A",
                severity="warning",
                message=f"Document has {self.structure.span_overuse} Span tags but few structural tags - content may be poorly tagged",
                fix_suggestion="Replace generic Span tags with semantic tags (P for paragraphs, H1-H6 for headings, etc.)",
                element_info={"span_count": self.structure.span_overuse, "structural_tags": total_content_tags},
                auto_fixable=True
            ))
    
    def _check_alt_text_quality(self):
        """
        Check quality of alt text - not just presence.
        """
        if self.structure.figures_with_empty_alt > 0:
            self.issues.append(PDFIssue(
                issue_type=PDFIssueType.EMPTY_ALT_TEXT,
                wcag_criterion="1.1.1",
                wcag_name="Non-text Content",
                wcag_level="A",
                severity="error",
                message=f"{self.structure.figures_with_empty_alt} figure(s) have empty or placeholder alt text",
                fix_suggestion="Provide meaningful descriptions for all images - alt text should convey the same information as the image",
                auto_fixable=False
            ))
    
    def _check_forms(self):
        """
        Check form field accessibility.
        WCAG 1.3.1 Info and Relationships (Level A)
        WCAG 3.3.2 Labels or Instructions (Level A)
        """
        doc = self._open_fitz()
        if not doc:
            return
        
        # Count form fields
        form_fields = 0
        for page in doc:
            widgets = page.widgets()
            if widgets:
                for widget in widgets:
                    form_fields += 1
        
        if form_fields > 0:
            self.issues.append(PDFIssue(
                issue_type=PDFIssueType.FORM_FIELDS_UNLABELED,
                wcag_criterion="3.3.2",
                wcag_name="Labels or Instructions",
                wcag_level="A",
                severity="warning",
                message=f"Document contains {form_fields} form field(s) - verify each has a label",
                fix_suggestion="Add tooltip text to each form field and ensure Form tags are present",
                element_info={"form_field_count": form_fields},
                auto_fixable=True
            ))
    
    def _check_tab_order(self):
        """
        Check that every page with annotations has /Tabs set to /S (structure).

        PDF/UA-1 clause 7.18.3 and PDF 1.7 §12.5 require that when a page
        contains annotations (links, form widgets, etc.) the page dictionary's
        /Tabs entry is set to /S so that the Tab key follows the document's
        logical structure tree rather than arbitrary PDF object order.

        Related: WCAG 2.4.3 Focus Order (Level A)
        """
        pike = self._open_pike()
        if not pike:
            return

        pages_without_s = 0
        affected_pages = []

        try:
            for page_num, page in enumerate(pike.pages):
                # Only check pages that have annotations
                if "/Annots" not in page:
                    continue
                annots = page["/Annots"]
                # annots could be an empty array – skip those
                if hasattr(annots, "__len__") and len(annots) == 0:
                    continue

                # Check /Tabs entry
                tabs = page.get("/Tabs")
                if tabs is None or str(tabs) != "/S":
                    pages_without_s += 1
                    affected_pages.append(page_num + 1)  # 1-based for reporting
        except Exception as e:
            logger.debug(f"Error checking tab order: {e}")
            return

        self.structure.tabs_not_s_count = pages_without_s

        if pages_without_s > 0:
            page_list = ", ".join(str(p) for p in affected_pages[:10])
            if len(affected_pages) > 10:
                page_list += f" … ({len(affected_pages)} total)"
            self.issues.append(PDFIssue(
                issue_type=PDFIssueType.TAB_ORDER_NOT_STRUCTURE,
                wcag_criterion="2.4.3",
                wcag_name="Focus Order",
                wcag_level="A",
                severity="error",
                message=(
                    f"{pages_without_s} page(s) with annotations do not have "
                    f"tab order set to \"S\" (structure): page(s) {page_list}"
                ),
                fix_suggestion=(
                    "Set the /Tabs entry to /S on every page dictionary that "
                    "contains annotations. This ensures the Tab key follows the "
                    "document structure tree rather than arbitrary PDF object order."
                ),
                element_info={
                    "pages_affected": affected_pages,
                    "total": pages_without_s,
                },
                auto_fixable=True,
            ))

    def _check_scanned_content(self):
        """
        Check for scanned/image-based content or unreadable text.
        WCAG 1.4.5 Images of Text (Level AA)
        """
        doc = self._open_fitz()
        if not doc:
            return

        scanned_pages = []

        for page_num, page in enumerate(doc):
            # 1. Check for non-embedded fonts or fonts with missing Unicode mapping
            try:
                fonts = page.get_fonts(full=True)
                has_bad_fonts = False
                for f in fonts:
                    # f is (xref, ext, type, name, username, encoding, is_embedded)
                    if len(f) >= 7:
                        f_xref = f[0]
                        f_type = f[2]
                        f_name = f[3]
                        f_encoding = f[5]
                        f_is_embedded = f[6]

                        # Flag if font is unnamed or bad
                        if not f_name or f_name == "n/a" or f_name == "":
                            has_bad_fonts = True
                            break

                        # Flag if font is not embedded (PDF/UA violation)
                        if f_is_embedded == 0:
                            has_bad_fonts = True
                            break

                        # Flag if font is embedded but lacks ToUnicode map and uses non-standard encoding
                        dict_str = doc.xref_object(f_xref)
                        if "ToUnicode" not in dict_str:
                            clean_encoding = f_encoding.replace("/", "") if isinstance(f_encoding, str) else ""
                            standard_encodings = {"WinAnsiEncoding", "MacRomanEncoding", "MacExpertEncoding", "StandardEncoding", "PDFDocEncoding"}
                            if f_type == "Type0" or clean_encoding in ("Identity-H", "Identity-V") or (clean_encoding and clean_encoding not in standard_encodings):
                                has_bad_fonts = True
                                break
                if has_bad_fonts:
                    scanned_pages.append(page_num)
                    continue
            except Exception:
                pass

            # 2. Check for pure scanned image pages
            text = page.get_text("text").strip()
            images = page.get_images()
            if len(images) > 0 and len(text) < 50:
                for img in images:
                    try:
                        rects = page.get_image_rects(img[0])
                        if rects:
                            img_area = rects[0].width * rects[0].height
                            page_area = page.rect.width * page.rect.height
                            if img_area > page_area * 0.5:
                                scanned_pages.append(page_num)
                                break
                    except Exception:
                        pass

        if scanned_pages:
            affected_pages = [p + 1 for p in scanned_pages]
            page_list = ", ".join(str(p) for p in affected_pages[:10])
            if len(affected_pages) > 10:
                page_list += f" … ({len(affected_pages)} total)"

            self.issues.append(PDFIssue(
                issue_type=PDFIssueType.SCANNED_IMAGE,
                wcag_criterion="1.4.5",
                wcag_name="Images of Text",
                wcag_level="AA",
                severity="error",
                message=f"{len(scanned_pages)} page(s) appear to be scanned images or have unreadable text: page(s) {page_list}",
                fix_suggestion="Run OCR (Recognize Text) to convert image to searchable text",
                page_number=scanned_pages[0] + 1,
                element_info={
                    "pages_affected": affected_pages,
                    "total": len(scanned_pages)
                },
                auto_fixable=True
            ))
    
    def _generate_report(self) -> Dict[str, Any]:
        """Generate comprehensive accessibility report."""
        # Count issues by severity
        errors = [i for i in self.issues if i.severity == "error"]
        warnings = [i for i in self.issues if i.severity == "warning"]
        
        # Count issues by WCAG level
        level_a = [i for i in self.issues if i.wcag_level == "A"]
        level_aa = [i for i in self.issues if i.wcag_level == "AA"]
        
        # Determine compliance status
        is_wcag_a_compliant = len([i for i in level_a if i.severity == "error"]) == 0
        is_wcag_aa_compliant = is_wcag_a_compliant and len([i for i in level_aa if i.severity == "error"]) == 0
        
        return {
            "metadata": {
                "title": self.metadata.title,
                "author": self.metadata.author,
                "language": self.metadata.language,
                "page_count": self.metadata.page_count,
                "file_size": self.metadata.file_size,
                "pdf_version": self.metadata.pdf_version,
                "is_tagged": self.metadata.is_tagged,
                "has_bookmarks": self.metadata.has_bookmarks,
            },
            "structure": {
                "has_structure_tree": self.structure.has_structure_tree,
                "tag_types": self.structure.tag_types,
                "figure_count": self.structure.figure_count,
                "figures_with_alt": self.structure.figures_with_alt,
                "table_count": self.structure.table_count,
                "tables_with_headers": self.structure.tables_with_headers,
                "heading_count": self.structure.heading_count,
                "link_count": self.structure.link_count,
            },
            "compliance": {
                "wcag_a_compliant": is_wcag_a_compliant,
                "wcag_aa_compliant": is_wcag_aa_compliant,
                "pdf_ua_compliant": self.metadata.is_tagged and is_wcag_a_compliant,
            },
            "summary": {
                "total_issues": len(self.issues),
                "errors": len(errors),
                "warnings": len(warnings),
                "auto_fixable": len([i for i in self.issues if i.auto_fixable]),
            },
            "issues": [
                {
                    "type": i.issue_type.value,
                    "wcag_criterion": i.wcag_criterion,
                    "wcag_name": i.wcag_name,
                    "wcag_level": i.wcag_level,
                    "severity": i.severity,
                    "message": i.message,
                    "fix_suggestion": i.fix_suggestion,
                    "page_number": i.page_number,
                    "element_info": i.element_info,
                    "auto_fixable": i.auto_fixable,
                }
                for i in self.issues
            ]
        }


class PDFRemediator:
    """
    PDF accessibility remediator.
    
    Can automatically fix certain accessibility issues.
    """
    
    def __init__(self, file_path: Path):
        """Initialize with PDF file path."""
        self.file_path = file_path
        self.changes: List[Dict[str, Any]] = []
    
    def fix_metadata(
        self,
        title: Optional[str] = None,
        language: Optional[str] = None,
        author: Optional[str] = None,
        subject: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Fix PDF metadata issues.
        
        WCAG 2.4.2 Page Titled
        WCAG 3.1.1 Language of Page
        """
        if not HAS_PIKEPDF:
            return {"success": False, "error": "pikepdf not installed"}
        
        try:
            with pikepdf.open(self.file_path, allow_overwriting_input=True) as pdf:
                # Set title
                if title:
                    with pdf.open_metadata() as meta:
                        meta['dc:title'] = title
                    self.changes.append({"type": "set_title", "value": title})
                    
                    if "/ViewerPreferences" not in pdf.Root:
                        pdf.Root.ViewerPreferences = pikepdf.Dictionary()
                    pdf.Root.ViewerPreferences["/DisplayDocTitle"] = True
                    self.changes.append({"type": "set_display_doc_title", "value": True})
                
                # Set language
                if language:
                    norm_lang = normalize_language_code(language)
                    pdf.Root.Lang = norm_lang
                    with pdf.open_metadata(set_pikepdf_as_editor=True, update_docinfo=True) as meta:
                        meta['dc:language'] = [norm_lang]
                    self.changes.append({"type": "set_language", "value": norm_lang})
                
                # Set author
                if author:
                    with pdf.open_metadata() as meta:
                        meta['dc:creator'] = [author]
                    self.changes.append({"type": "set_author", "value": author})
                
                # Set subject
                if subject:
                    with pdf.open_metadata() as meta:
                        meta['dc:description'] = subject
                    self.changes.append({"type": "set_subject", "value": subject})
                
                pdf.save()
            
            return {
                "success": True,
                "changes": self.changes,
                "message": f"Applied {len(self.changes)} metadata fix(es)"
            }
            
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def auto_tag_document(
        self,
        output_path: Optional[Path] = None,
        model_path: str = "",
        confidence_threshold: float = 0.0,
    ) -> Dict[str, Any]:
        """
        Automatically tag a PDF using OpenDataLoader layout extraction.

        WCAG 1.3.1 Info and Relationships (Level A)
        PDF/UA Requirement: Document must be tagged.

        Args:
            output_path: Where to save the tagged PDF. Defaults to overwriting
                         the source file.
            model_path: Legacy compatibility argument; ignored.
            confidence_threshold: Legacy compatibility argument; ignored.

        Returns:
            Dict with success status, tag counts, and any errors.
        """
        target = output_path or self.file_path

        try:
            from .pdf_auto_tagging import auto_tag_pdf

            result = auto_tag_pdf(self.file_path, output_path=target, overwrite_tags=True)

            if result.get("success") and not result.get("skipped"):
                self.changes.append({
                    "type": "auto_tag",
                    "tags_created": result.get("tags_created", 0),
                    "tag_counts": result.get("tag_counts", {}),
                    "pages_processed": result.get("pages_processed", 0),
                })
            return result
        except Exception as e:
            logger.error(f"Auto-tagging failed: {e}")
            return {"success": False, "error": str(e), "output_path": str(target)}

    def generate_bookmarks_from_headings(self) -> Dict[str, Any]:
        """
        Generate bookmarks from heading structure.
        
        WCAG 2.4.5 Multiple Ways
        """
        if not HAS_PYMUPDF or not HAS_PIKEPDF:
            return {"success": False, "error": "Required libraries not installed"}
        
        try:
            # First, extract headings with PyMuPDF
            doc = fitz.open(str(self.file_path))
            
            from collections import Counter

            # Find heading size threshold dynamically based on body size
            sizes = []
            for page in doc:
                for block in page.get_text("dict").get("blocks", []):
                    if "lines" not in block:
                        continue
                    for line in block["lines"]:
                        for span in line.get("spans", []):
                            text = span.get("text", "").strip()
                            if len(text) > 15:
                                sizes.append(round(span.get("size", 12), 1))
            
            most_common_size = 12.0
            if sizes:
                counter = Counter(sizes)
                most_common_size = counter.most_common(1)[0][0]
            threshold = max(most_common_size + 1.5, 12.5)

            # Collect candidate headings
            candidates = []
            for page_num, page in enumerate(doc):
                blocks = page.get_text("dict", sort=True).get("blocks", [])
                for block in blocks:
                    if "lines" not in block:
                        continue
                    
                    current_heading_parts = []
                    block_max_size = 0
                    block_is_bold = False
                    block_y_coord = 0.0
                    
                    for line in block["lines"]:
                        line_text_parts = []
                        line_max_size = 0
                        line_is_bold = False
                        line_y_coord = 0.0
                        
                        for span in line.get("spans", []):
                            span_text = span.get("text", "").strip()
                            if not span_text:
                                continue
                            
                            size = span.get("size", 12)
                            font = span.get("font", "")
                            flags = span.get("flags", 0)
                            span_bold = "bold" in font.lower() or (flags & 16)
                            
                            line_text_parts.append(span_text)
                            if size > line_max_size:
                                line_max_size = size
                                line_is_bold = span_bold
                                if "bbox" in span and len(span["bbox"]) > 1:
                                    line_y_coord = span["bbox"][1]
                        
                        line_text = " ".join(line_text_parts).strip()
                        if not line_text:
                            continue
                        
                        # Line is heading-like if size >= threshold AND (is bold OR size >= 18)
                        if line_max_size >= threshold and (line_is_bold or line_max_size >= 18.0):
                            if not current_heading_parts:
                                block_y_coord = line_y_coord
                            current_heading_parts.append(line_text)
                            if line_max_size > block_max_size:
                                block_max_size = line_max_size
                                block_is_bold = line_is_bold
                        else:
                            if current_heading_parts:
                                heading_text = " ".join(current_heading_parts).strip()
                                if 3 <= len(heading_text) <= 150:
                                    candidates.append({
                                        "text": heading_text,
                                        "page": page_num + 1,
                                        "y": block_y_coord,
                                        "size": block_max_size
                                    })
                                current_heading_parts = []
                    
                    if current_heading_parts:
                        heading_text = " ".join(current_heading_parts).strip()
                        if 3 <= len(heading_text) <= 150:
                            candidates.append({
                                "text": heading_text,
                                "page": page_num + 1,
                                "y": block_y_coord,
                                "size": block_max_size
                            })

            doc.close()

            if not candidates:
                return {
                    "success": False,
                    "error": "No headings found to create bookmarks"
                }

            # Group size categories to assign logical levels (1, 2, 3...)
            unique_sizes = sorted(list(set(round(c["size"], 1) for c in candidates)), reverse=True)
            
            # Merge sizes within 1.0pt of each other
            size_groups = []
            for sz in unique_sizes:
                added = False
                for g in size_groups:
                    if abs(g[0] - sz) <= 1.0:
                        g.append(sz)
                        added = True
                        break
                if not added:
                    size_groups.append([sz])
                    
            group_avg_sizes = [sum(g) / len(g) for g in size_groups]
            
            # Check pages where each size group appears
            group_pages = []
            for g in size_groups:
                pages = set()
                for c in candidates:
                    if round(c["size"], 1) in g:
                        pages.add(c["page"])
                group_pages.append(pages)
                
            # Level mapping
            group_levels = {}
            current_level = 1
            for idx, (avg_sz, pages) in enumerate(zip(group_avg_sizes, group_pages)):
                if idx == 0 and pages == {1} and len(group_avg_sizes) > 1:
                    # Page 1 only -> Cover Title -> Level 1
                    group_levels[idx] = 1
                else:
                    group_levels[idx] = current_level
                    current_level += 1

            toc = []
            for c in candidates:
                c_sz = round(c["size"], 1)
                group_idx = -1
                for idx, g in enumerate(size_groups):
                    if c_sz in g:
                        group_idx = idx
                        break
                level = group_levels.get(group_idx, 1)
                toc.append([level, c["text"], c["page"], c["y"]])

            if toc and toc[0][0] > 1:
                toc[0][0] = 1
            
            # Add bookmarks with PyMuPDF cleanly to avoid incremental corruption
            doc = fitz.open(str(self.file_path))
            doc.set_toc(toc)
            tmp_path = str(self.file_path) + ".tmp"
            doc.save(tmp_path, encryption=0)
            doc.close()
            import shutil
            shutil.move(tmp_path, str(self.file_path))
            
            self.changes.append({
                "type": "add_bookmarks",
                "count": len(toc)
            })
            
            return {
                "success": True,
                "bookmarks_added": len(toc),
                "message": f"Added {len(toc)} bookmarks"
            }
                
        except Exception as e:
            return {"success": False, "error": str(e)}


def analyze_pdf(file_path: Path) -> Dict[str, Any]:
    """
    Convenience function to analyze a PDF file.
    
    Args:
        file_path: Path to PDF file
        
    Returns:
        Accessibility analysis report
    """
    analyzer = PDFAccessibilityAnalyzer(file_path=file_path)
    try:
        return analyzer.analyze()
    finally:
        analyzer.close()


def remediate_pdf(
    file_path: Path,
    title: Optional[str] = None,
    language: Optional[str] = None,
    add_bookmarks: bool = False
) -> Dict[str, Any]:
    """
    Convenience function to remediate a PDF file.
    
    Args:
        file_path: Path to PDF file
        title: Document title to set
        language: Document language to set (e.g., "en", "es")
        add_bookmarks: Whether to generate bookmarks from headings
        
    Returns:
        Remediation results
    """
    remediator = PDFRemediator(file_path)
    results = {"metadata": None, "bookmarks": None}
    
    if title or language:
        results["metadata"] = remediator.fix_metadata(title=title, language=language)
    
    if add_bookmarks:
        results["bookmarks"] = remediator.generate_bookmarks_from_headings()
    
    return results

