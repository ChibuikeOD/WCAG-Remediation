"""
PDF Parser for WCAG Accessibility Analysis.

This module provides utilities for parsing and extracting accessibility-relevant
information from PDF documents using PyMuPDF and pikepdf.
"""
import re
from typing import Optional, Dict, Any, List, Tuple
from pathlib import Path
import logging

try:
    import fitz  # PyMuPDF
    HAS_PYMUPDF = True
except ImportError:
    HAS_PYMUPDF = False

try:
    import pikepdf
    HAS_PIKEPDF = True
except ImportError:
    HAS_PIKEPDF = False

logger = logging.getLogger(__name__)


class PDFParser:
    """
    Parser for PDF documents with accessibility-focused extraction.
    
    Provides methods for:
    - Extracting document metadata and structure
    - Analyzing tagged PDF structure
    - Identifying accessibility issues
    """
    
    def __init__(self, file_path: Optional[Path] = None, file_bytes: Optional[bytes] = None):
        """
        Initialize parser with PDF file path or bytes.
        
        Args:
            file_path: Path to PDF file
            file_bytes: Raw PDF bytes
        """
        self.file_path = file_path
        self.file_bytes = file_bytes
        self._doc = None
        self._pike_pdf = None
        
        if not HAS_PYMUPDF:
            logger.warning("PyMuPDF not installed. PDF analysis capabilities limited.")
        
        if not HAS_PIKEPDF:
            logger.warning("pikepdf not installed. PDF metadata extraction limited.")
    
    def _get_doc(self):
        """Lazy-load PyMuPDF document."""
        if self._doc is None and HAS_PYMUPDF:
            if self.file_path:
                self._doc = fitz.open(str(self.file_path))
            elif self.file_bytes:
                self._doc = fitz.open(stream=self.file_bytes, filetype="pdf")
        return self._doc
    
    def _get_pike_pdf(self):
        """Lazy-load pikepdf document for metadata."""
        if self._pike_pdf is None and HAS_PIKEPDF:
            if self.file_path:
                self._pike_pdf = pikepdf.open(str(self.file_path))
            elif self.file_bytes:
                from io import BytesIO
                self._pike_pdf = pikepdf.open(BytesIO(self.file_bytes))
        return self._pike_pdf
    
    def close(self):
        """Close open document handles."""
        if self._doc:
            self._doc.close()
            self._doc = None
        if self._pike_pdf:
            self._pike_pdf.close()
            self._pike_pdf = None
    
    def get_document_metadata(self) -> Dict[str, Any]:
        """
        Extract document metadata relevant for accessibility.
        
        Returns metadata including:
        - title
        - author
        - language
        - tagged status
        - page count
        
        WCAG 2.4.2 Page Titled
        WCAG 3.1.1 Language of Page
        """
        metadata = {
            "title": None,
            "author": None,
            "subject": None,
            "keywords": None,
            "creator": None,
            "producer": None,
            "language": None,
            "page_count": 0,
            "is_tagged": False,
            "has_outline": False,
            "is_encrypted": False,
            "pdf_version": None,
        }
        
        doc = self._get_doc()
        if doc:
            # Basic metadata from PyMuPDF
            metadata["page_count"] = len(doc)
            metadata["is_encrypted"] = doc.is_encrypted
            
            # Document info
            info = doc.metadata
            if info:
                metadata["title"] = info.get("title")
                metadata["author"] = info.get("author")
                metadata["subject"] = info.get("subject")
                metadata["keywords"] = info.get("keywords")
                metadata["creator"] = info.get("creator")
                metadata["producer"] = info.get("producer")
            
            # Check for outline (bookmarks) - WCAG 2.4.5 Multiple Ways
            metadata["has_outline"] = len(doc.get_toc()) > 0
            
            # Check if tagged - critical for PDF/UA compliance
            try:
                catalog = doc.pdf_catalog()
                if catalog:
                    mark_info = doc.xref_get_key(catalog, "MarkInfo")
                    if mark_info[0] != 'null':
                        metadata["is_tagged"] = True
            except Exception:
                pass
        
        # Get more metadata from pikepdf
        pike = self._get_pike_pdf()
        if pike:
            metadata["pdf_version"] = f"{pike.pdf_version}"
            
            # Language from document catalog - WCAG 3.1.1
            try:
                if '/Lang' in pike.Root:
                    metadata["language"] = str(pike.Root.Lang)
            except Exception:
                pass
        
        return metadata
    
    def check_tagged_structure(self) -> Dict[str, Any]:
        """
        Analyze the tagged PDF structure for accessibility.
        
        PDF/UA compliance requires proper document structure tags.
        
        WCAG 1.3.1 Info and Relationships
        """
        structure = {
            "is_tagged": False,
            "has_structure_tree": False,
            "tag_types": [],
            "heading_structure": [],
            "has_alt_text_elements": False,
            "figures_count": 0,
            "figures_with_alt": 0,
            "tables_count": 0,
            "lists_count": 0,
        }
        
        pike = self._get_pike_pdf()
        if not pike:
            return structure
        
        try:
            # Check for MarkInfo
            if '/MarkInfo' in pike.Root:
                mark_info = pike.Root.MarkInfo
                if '/Marked' in mark_info:
                    structure["is_tagged"] = bool(mark_info.Marked)
            
            # Check for structure tree root
            if '/StructTreeRoot' in pike.Root:
                structure["has_structure_tree"] = True
                struct_root = pike.Root.StructTreeRoot
                
                # Analyze structure elements
                self._analyze_struct_element(struct_root, structure)
                
        except Exception as e:
            logger.debug(f"Error analyzing PDF structure: {e}")
        
        return structure
    
    def _analyze_struct_element(self, element, structure: Dict, depth: int = 0):
        """Recursively analyze structure tree elements."""
        try:
            if '/K' in element:
                kids = element.K
                if not isinstance(kids, list):
                    kids = [kids]
                
                for kid in kids:
                    if hasattr(kid, 'keys'):
                        if '/S' in kid:
                            tag_type = str(kid.S)
                            
                            if tag_type not in structure["tag_types"]:
                                structure["tag_types"].append(tag_type)
                            
                            # Count specific elements
                            if tag_type == '/Figure':
                                structure["figures_count"] += 1
                                if '/Alt' in kid:
                                    structure["figures_with_alt"] += 1
                                    structure["has_alt_text_elements"] = True
                            elif tag_type == '/Table':
                                structure["tables_count"] += 1
                            elif tag_type == '/L':  # List
                                structure["lists_count"] += 1
                            elif tag_type in ['/H1', '/H2', '/H3', '/H4', '/H5', '/H6']:
                                level = int(tag_type[2])
                                structure["heading_structure"].append({
                                    "level": level,
                                    "depth": depth
                                })
                        
                        # Recurse
                        if depth < 10:  # Prevent infinite recursion
                            self._analyze_struct_element(kid, structure, depth + 1)
        except Exception:
            pass
    
    def extract_text_by_page(self) -> List[Dict[str, Any]]:
        """
        Extract text content from each page.
        
        WCAG 1.4.5 Images of Text
        """
        pages = []
        
        doc = self._get_doc()
        if not doc:
            return pages
        
        for page_num, page in enumerate(doc):
            text = page.get_text("text")
            
            # Get text blocks with positions
            blocks = page.get_text("dict")["blocks"]
            
            pages.append({
                "page_number": page_num + 1,
                "text": text,
                "text_length": len(text),
                "has_text": len(text.strip()) > 0,
                "block_count": len(blocks),
            })
        
        return pages
    
    def extract_images(self) -> List[Dict[str, Any]]:
        """
        Extract information about images in the PDF.
        
        WCAG 1.1.1 Non-text Content
        """
        images = []
        
        doc = self._get_doc()
        if not doc:
            return images
        
        for page_num, page in enumerate(doc):
            image_list = page.get_images()
            
            for img_index, img in enumerate(image_list):
                xref = img[0]
                
                # Get image info
                try:
                    base_image = doc.extract_image(xref)
                    images.append({
                        "page_number": page_num + 1,
                        "image_index": img_index,
                        "width": base_image.get("width"),
                        "height": base_image.get("height"),
                        "colorspace": base_image.get("colorspace"),
                        "xref": xref,
                        # Alt text would need to come from structure tree
                        "has_alt_text": False,  # Determined separately
                    })
                except Exception:
                    pass
        
        return images
    
    def extract_links(self) -> List[Dict[str, Any]]:
        """
        Extract hyperlinks from the PDF.
        
        WCAG 2.4.4 Link Purpose (In Context)
        """
        links = []
        
        doc = self._get_doc()
        if not doc:
            return links
        
        for page_num, page in enumerate(doc):
            page_links = page.get_links()
            
            for link in page_links:
                links.append({
                    "page_number": page_num + 1,
                    "uri": link.get("uri"),
                    "kind": link.get("kind"),  # 0=goto, 1=uri, 2=launch, etc.
                    "rect": link.get("from"),  # Bounding box
                })
        
        return links
    
    def check_reading_order(self) -> Dict[str, Any]:
        """
        Analyze reading order in the PDF.
        
        WCAG 1.3.2 Meaningful Sequence
        """
        reading_order = {
            "has_logical_order": False,
            "uses_column_layout": False,
            "potential_issues": [],
        }
        
        doc = self._get_doc()
        if not doc:
            return reading_order
        
        for page_num, page in enumerate(doc):
            # Get text blocks with positions
            blocks = page.get_text("dict")["blocks"]
            
            if len(blocks) > 1:
                # Check for multi-column layout
                x_positions = []
                for block in blocks:
                    if "bbox" in block:
                        x_positions.append(block["bbox"][0])
                
                # If we have significant x-position variation, might be columns
                if x_positions:
                    x_range = max(x_positions) - min(x_positions)
                    page_width = page.rect.width
                    
                    if x_range > page_width * 0.3:
                        reading_order["uses_column_layout"] = True
                        reading_order["potential_issues"].append({
                            "page": page_num + 1,
                            "issue": "Multi-column layout detected - verify reading order"
                        })
        
        # If tagged, reading order is more likely to be correct
        structure = self.check_tagged_structure()
        reading_order["has_logical_order"] = structure["is_tagged"]
        
        return reading_order
    
    def check_color_contrast(self) -> List[Dict[str, Any]]:
        """
        Attempt to check color contrast in the PDF.
        
        Note: This is limited - full contrast analysis requires rendering.
        
        WCAG 1.4.3 Contrast (Minimum)
        """
        contrast_issues = []
        
        doc = self._get_doc()
        if not doc:
            return contrast_issues
        
        for page_num, page in enumerate(doc):
            # Get text with color information
            try:
                text_dict = page.get_text("dict")
                
                for block in text_dict.get("blocks", []):
                    if "lines" in block:
                        for line in block["lines"]:
                            for span in line.get("spans", []):
                                color = span.get("color")
                                # Color analysis would go here
                                # This is a simplified check
                                
            except Exception:
                pass
        
        return contrast_issues
    
    def get_accessibility_summary(self) -> Dict[str, Any]:
        """
        Get a comprehensive accessibility summary of the PDF.
        
        Combines all checks into a single report.
        """
        metadata = self.get_document_metadata()
        structure = self.check_tagged_structure()
        reading_order = self.check_reading_order()
        images = self.extract_images()
        links = self.extract_links()
        pages = self.extract_text_by_page()
        
        issues = []
        
        # Check for title - WCAG 2.4.2
        if not metadata.get("title"):
            issues.append({
                "rule_id": "2.4.2",
                "wcag_criterion": "2.4.2",
                "wcag_name": "Page Titled",
                "wcag_level": "A",
                "message": "PDF is missing document title",
                "severity": "error",
                "auto_fixable": True
            })
        
        # Check for language - WCAG 3.1.1
        if not metadata.get("language"):
            issues.append({
                "rule_id": "3.1.1",
                "wcag_criterion": "3.1.1",
                "wcag_name": "Language of Page",
                "wcag_level": "A",
                "message": "PDF is missing language specification",
                "severity": "error",
                "auto_fixable": True
            })
        
        # Check if tagged - WCAG 1.3.1
        if not structure.get("is_tagged"):
            issues.append({
                "rule_id": "1.3.1",
                "wcag_criterion": "1.3.1",
                "wcag_name": "Info and Relationships",
                "wcag_level": "A",
                "message": "PDF is not tagged - structure cannot be programmatically determined",
                "severity": "error",
                "auto_fixable": True
            })
        
        # Check for alt text on figures - WCAG 1.1.1
        if structure.get("figures_count", 0) > structure.get("figures_with_alt", 0):
            missing = structure["figures_count"] - structure["figures_with_alt"]
            issues.append({
                "rule_id": "1.1.1",
                "wcag_criterion": "1.1.1",
                "wcag_name": "Non-text Content",
                "wcag_level": "A",
                "message": f"{missing} figure(s) missing alternative text",
                "severity": "error",
                "auto_fixable": False
            })
        
        # Check for bookmarks - WCAG 2.4.5
        if metadata.get("page_count", 0) > 20 and not metadata.get("has_outline"):
            issues.append({
                "rule_id": "2.4.5",
                "wcag_criterion": "2.4.5",
                "wcag_name": "Multiple Ways",
                "wcag_level": "AA",
                "message": "Large document without bookmarks/outline",
                "severity": "warning",
                "auto_fixable": True
            })
        
        return {
            "metadata": metadata,
            "structure": structure,
            "reading_order": reading_order,
            "image_count": len(images),
            "link_count": len(links),
            "page_count": len(pages),
            "issues": issues,
        }



