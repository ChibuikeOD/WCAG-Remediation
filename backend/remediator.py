"""
Accessibility Remediator.

Applies automated fixes for accessibility issues where possible.

Supports remediation for:
- Missing alt attributes (WCAG 1.1.1)
- Missing form labels (WCAG 1.3.1, 3.3.2)
- Missing language attributes (WCAG 3.1.1)
- Missing page titles (WCAG 2.4.2)
- Contrast adjustments (WCAG 1.4.3)
"""
from typing import Dict, Any, List, Optional, Tuple
from bs4 import BeautifulSoup, Tag
from pathlib import Path
import logging
import re

from .models import (
    AccessibilityIssue, RemediationResult, AccessibilityReport,
    IssueStatus, Severity
)
from .rules_engine import ColorUtils

logger = logging.getLogger(__name__)


def normalize_language_code(lang: Optional[str]) -> str:
    """Normalize language name/code to a PAC-friendly BCP 47 language tag."""
    if not lang:
        return "en-US"
    
    lang = lang.strip().replace("_", "-")
    if not lang:
        return "en-US"
    lower = lang.lower()
    
    # Common language name to code mapping
    name_to_code = {
        "english": "en-US",
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
    
    if lower in name_to_code:
        return name_to_code[lower]
    
    if lower == "en":
        return "en-US"
    
    if re.fullmatch(r"[a-zA-Z]{2,3}(?:-[a-zA-Z0-9]{1,8})*", lang):
        parts = lower.split("-")
        for index, part in enumerate(parts[1:], start=1):
            if index == 1 and len(part) == 2 and part.isalpha():
                parts[index] = part.upper()
            elif index == 1 and len(part) == 4 and part.isalpha():
                parts[index] = part.title()
        return "-".join(parts)
        
    return "en-US"



class HTMLRemediator:
    """
    Applies automated fixes to HTML documents.
    """
    
    def __init__(self, html_content: str):
        """
        Initialize the remediator with HTML content.
        
        Args:
            html_content: The HTML to remediate
        """
        self.original_html = html_content
        self.soup = BeautifulSoup(html_content, 'html5lib')
        self.changes: List[Dict[str, Any]] = []
    
    def apply_fixes(self, issues: List[AccessibilityIssue]) -> List[RemediationResult]:
        """
        Apply automated fixes for the given issues.
        
        Args:
            issues: List of accessibility issues to fix
            
        Returns:
            List of remediation results
        """
        results = []
        
        for issue in issues:
            if not issue.automatable_fix:
                continue
            
            result = self._apply_fix(issue)
            results.append(result)
        
        return results
    
    def _apply_fix(self, issue: AccessibilityIssue) -> RemediationResult:
        """
        Apply a fix for a single issue.
        
        Args:
            issue: The issue to fix
            
        Returns:
            RemediationResult indicating success/failure
        """
        rule_id = issue.rule_id
        
        try:
            # Route to appropriate fix method
            if rule_id == "1.1.1":
                return self._fix_missing_alt(issue)
            elif rule_id == "2.4.2":
                return self._fix_missing_title(issue)
            elif rule_id == "3.1.1":
                return self._fix_missing_lang(issue)
            elif rule_id in ["1.3.1", "3.3.2"]:
                return self._fix_missing_label(issue)
            elif rule_id == "1.4.3":
                return self._fix_contrast(issue)
            elif rule_id == "4.1.2":
                return self._fix_missing_name(issue)
            else:
                return RemediationResult(
                    issue_id=issue.id,
                    success=False,
                    message=f"No automated fix available for rule {rule_id}"
                )
        except Exception as e:
            logger.error(f"Error applying fix for {rule_id}: {e}")
            return RemediationResult(
                issue_id=issue.id,
                success=False,
                message=f"Error applying fix: {str(e)}"
            )
    
    def _fix_missing_alt(self, issue: AccessibilityIssue) -> RemediationResult:
        """
        Fix missing alt attribute on images.
        
        WCAG 1.1.1 Non-text Content
        """
        if not issue.element_location or not issue.element_location.selector:
            return RemediationResult(
                issue_id=issue.id,
                success=False,
                message="Cannot locate element"
            )
        
        # Find the element
        element = self._find_element(issue)
        if not element:
            return RemediationResult(
                issue_id=issue.id,
                success=False,
                message="Element not found in document"
            )
        
        # Generate alt text placeholder
        src = element.get('src', '')
        filename = Path(src).stem if src else 'image'
        
        # Clean up filename for alt text
        alt_text = re.sub(r'[-_]', ' ', filename).title()
        alt_text = f"[Image: {alt_text}]"
        
        original = str(element)
        element['alt'] = alt_text
        
        self.changes.append({
            "type": "add_alt",
            "element": str(element),
            "alt_text": alt_text
        })
        
        return RemediationResult(
            issue_id=issue.id,
            success=True,
            message=f"Added alt attribute: {alt_text}",
            original_value=None,
            new_value=alt_text
        )
    
    def _fix_missing_title(self, issue: AccessibilityIssue) -> RemediationResult:
        """
        Fix missing page title.
        
        WCAG 2.4.2 Page Titled
        """
        head = self.soup.find('head')
        if not head:
            head = self.soup.new_tag('head')
            if self.soup.html:
                self.soup.html.insert(0, head)
            else:
                return RemediationResult(
                    issue_id=issue.id,
                    success=False,
                    message="Cannot create head element"
                )
        
        title = head.find('title')
        if not title:
            title = self.soup.new_tag('title')
            head.insert(0, title)
        
        if not title.string or not title.string.strip():
            title.string = "[Page Title Required]"
            
            self.changes.append({
                "type": "add_title",
                "title": title.string
            })
            
            return RemediationResult(
                issue_id=issue.id,
                success=True,
                message="Added placeholder page title",
                original_value=None,
                new_value=title.string
            )
        
        return RemediationResult(
            issue_id=issue.id,
            success=False,
            message="Title already exists"
        )
    
    def _fix_missing_lang(self, issue: AccessibilityIssue) -> RemediationResult:
        """
        Fix missing language attribute on html element.
        
        WCAG 3.1.1 Language of Page
        """
        html = self.soup.find('html')
        if not html:
            return RemediationResult(
                issue_id=issue.id,
                success=False,
                message="No html element found"
            )
        
        if not html.get('lang'):
            html['lang'] = 'en'
            
            self.changes.append({
                "type": "add_lang",
                "lang": "en"
            })
            
            return RemediationResult(
                issue_id=issue.id,
                success=True,
                message="Added lang='en' attribute (update if different language)",
                original_value=None,
                new_value="en"
            )
        
        return RemediationResult(
            issue_id=issue.id,
            success=False,
            message="Language attribute already exists"
        )
    
    def _fix_missing_label(self, issue: AccessibilityIssue) -> RemediationResult:
        """
        Fix missing form labels.
        
        WCAG 1.3.1 Info and Relationships
        WCAG 3.3.2 Labels or Instructions
        """
        element = self._find_element(issue)
        if not element:
            return RemediationResult(
                issue_id=issue.id,
                success=False,
                message="Element not found"
            )
        
        # Generate ID if missing
        if not element.get('id'):
            name = element.get('name', element.get('type', 'input'))
            element['id'] = f"wcag-fix-{name}"
        
        element_id = element['id']
        
        # Check if label already exists
        existing_label = self.soup.find('label', attrs={'for': element_id})
        if existing_label:
            return RemediationResult(
                issue_id=issue.id,
                success=False,
                message="Label already exists"
            )
        
        # Create label
        label_text = element.get('name', element.get('type', 'Input'))
        label_text = re.sub(r'[-_]', ' ', label_text).title()
        
        label = self.soup.new_tag('label')
        label['for'] = element_id
        label.string = f"[Label: {label_text}]"
        
        # Insert label before input
        element.insert_before(label)
        
        self.changes.append({
            "type": "add_label",
            "for": element_id,
            "label_text": label.string
        })
        
        return RemediationResult(
            issue_id=issue.id,
            success=True,
            message=f"Added label for {element_id}",
            original_value=None,
            new_value=str(label)
        )
    
    def _fix_contrast(self, issue: AccessibilityIssue) -> RemediationResult:
        """
        Attempt to fix contrast issues.
        
        WCAG 1.4.3 Contrast (Minimum)
        
        Note: This is a simplified fix that suggests inline styles.
        A better approach would be to modify CSS.
        """
        evidence = issue.evidence or {}
        current_ratio = evidence.get('contrast_ratio', 0)
        fg_color = evidence.get('foreground_color', '')
        bg_color = evidence.get('background_color', '')
        
        if not fg_color or not bg_color:
            return RemediationResult(
                issue_id=issue.id,
                success=False,
                message="Cannot determine colors to fix"
            )
        
        # Suggest improved colors
        # For simplicity, we suggest black on white or white on black
        suggestion = ""
        if self._get_luminance(bg_color) > 0.5:
            suggestion = "color: #000000;"  # Dark text on light background
        else:
            suggestion = "color: #ffffff;"  # Light text on dark background
        
        return RemediationResult(
            issue_id=issue.id,
            success=True,
            message=f"Suggested contrast fix: Add inline style '{suggestion}'",
            original_value=fg_color,
            new_value=suggestion
        )
    
    def _fix_missing_name(self, issue: AccessibilityIssue) -> RemediationResult:
        """
        Fix missing accessible name on interactive elements.
        
        WCAG 4.1.2 Name, Role, Value
        """
        element = self._find_element(issue)
        if not element:
            return RemediationResult(
                issue_id=issue.id,
                success=False,
                message="Element not found"
            )
        
        # Generate accessible name based on context
        tag_name = element.name
        name = element.get('name', element.get('id', tag_name))
        name = re.sub(r'[-_]', ' ', name).title()
        
        element['aria-label'] = f"[{name}]"
        
        self.changes.append({
            "type": "add_aria_label",
            "element": tag_name,
            "label": element['aria-label']
        })
        
        return RemediationResult(
            issue_id=issue.id,
            success=True,
            message=f"Added aria-label: {element['aria-label']}",
            original_value=None,
            new_value=element['aria-label']
        )
    
    def _find_element(self, issue: AccessibilityIssue) -> Optional[Tag]:
        """Find an element in the document based on issue location."""
        if not issue.element_location:
            return None
        
        location = issue.element_location
        
        # Try to find by HTML snippet
        if location.html_snippet:
            # Extract tag and attributes from snippet
            match = re.match(r'<(\w+)', location.html_snippet)
            if match:
                tag = match.group(1)
                
                # Try to find by ID first
                id_match = re.search(r'id=["\']([^"\']+)["\']', location.html_snippet)
                if id_match:
                    element = self.soup.find(id=id_match.group(1))
                    if element:
                        return element
                
                # Try by class
                class_match = re.search(r'class=["\']([^"\']+)["\']', location.html_snippet)
                if class_match:
                    elements = self.soup.find_all(tag, class_=class_match.group(1).split()[0])
                    if len(elements) == 1:
                        return elements[0]
        
        # Try by selector
        if location.selector:
            try:
                elements = self.soup.select(location.selector)
                if len(elements) == 1:
                    return elements[0]
            except Exception:
                pass
        
        return None
    
    def _get_luminance(self, hex_color: str) -> float:
        """Get relative luminance of a color."""
        try:
            rgb = ColorUtils.hex_to_rgb(hex_color)
            return ColorUtils.rgb_to_relative_luminance(*rgb)
        except Exception:
            return 0.5
    
    def get_remediated_html(self) -> str:
        """Get the remediated HTML content."""
        return str(self.soup)
    
    def get_change_summary(self) -> Dict[str, Any]:
        """Get a summary of changes made."""
        return {
            "total_changes": len(self.changes),
            "changes": self.changes
        }


class PDFRemediator:
    """
    Applies automated fixes to PDF documents.
    
    Note: PDF remediation is more limited and often requires
    manual intervention or specialized tools.
    """
    
    def __init__(self, file_path: Path):
        """Initialize with PDF file path."""
        self.file_path = file_path
        self.changes: List[Dict[str, Any]] = []
    
    def fix_metadata(self, title: Optional[str] = None, language: Optional[str] = None) -> List[RemediationResult]:
        """
        Fix PDF metadata issues.
        
        WCAG 2.4.2 Page Titled
        WCAG 3.1.1 Language of Page
        """
        results = []
        
        try:
            import pikepdf
            
            with pikepdf.open(self.file_path, allow_overwriting_input=True) as pdf:
                # Fix title
                if title:
                    with pdf.open_metadata() as meta:
                        meta['dc:title'] = title
                    if "/ViewerPreferences" not in pdf.Root:
                        pdf.Root.ViewerPreferences = pikepdf.Dictionary()
                    pdf.Root.ViewerPreferences["/DisplayDocTitle"] = True
                    results.append(RemediationResult(
                        issue_id="pdf-title",
                        success=True,
                        message=f"Added document title: {title} (and enabled DisplayDocTitle)",
                        new_value=title
                    ))
                    self.changes.append({"type": "add_title", "title": title})
                
                # Fix language
                if language:
                    norm_lang = normalize_language_code(language)
                    pdf.Root.Lang = norm_lang
                    with pdf.open_metadata(set_pikepdf_as_editor=True, update_docinfo=True) as meta:
                        meta['dc:language'] = [norm_lang]
                    results.append(RemediationResult(
                        issue_id="pdf-lang",
                        success=True,
                        message=f"Added document language: {norm_lang}",
                        new_value=norm_lang
                    ))
                    self.changes.append({"type": "add_lang", "lang": norm_lang})
                
                pdf.save()
                
        except ImportError:
            results.append(RemediationResult(
                issue_id="pdf-error",
                success=False,
                message="pikepdf not installed"
            ))
        except Exception as e:
            results.append(RemediationResult(
                issue_id="pdf-error",
                success=False,
                message=f"Error fixing PDF: {str(e)}"
            ))
        
        return results
    
    def auto_tag_document(
        self,
        output_path: Optional[Path] = None,
        model_path: str = "",
        confidence_threshold: float = 0.0,
        overwrite_tags: bool = True,
    ) -> Dict[str, Any]:
        """
        Automatically tag a PDF using the fine-tuned LayoutLMv3 model.

        WCAG 1.3.1 Info and Relationships (Level A)

        Args:
            output_path: Where to save the tagged PDF (defaults to self.file_path).
            model_path: Optional path to model directory (defaults to layoutLM_trained).
            confidence_threshold: Minimum per-token confidence to keep a label.
            overwrite_tags: Rebuild an existing structure tree when True.

        Returns:
            Dict with success status, tag counts, and any errors.
        """
        target = output_path or self.file_path

        try:
            from .pdf_auto_tagging import auto_tag_pdf

            result = auto_tag_pdf(
                target,
                output_path=target,
                overwrite_tags=overwrite_tags,
                model_path=model_path,
                confidence_threshold=confidence_threshold,
            )

            if result.get("success") and not result.get("skipped"):
                self.changes.append({
                    "type": "auto_tag",
                    "tags_created": result.get("tags_created", 0),
                    "tag_counts": result.get("tag_counts", {}),
                    "pages_processed": result.get("pages_processed", 0),
                })
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Auto-tagging failed: {e}")
            return {"success": False, "error": str(e), "output_path": str(target)}

        return result

    def fix_all(
        self,
        output_path: Optional[Path] = None,
        report: Optional[Any] = None,
        original_filename: str = "",
        overwrite_tags: bool = True,
    ) -> List[RemediationResult]:
        """
        Run the full PDF remediation pipeline: metadata, auto-tag, structural
        fixes, bookmarks, OCR, and form labels.  Returns a flat list of
        RemediationResult for every fix attempted.

        Args:
            overwrite_tags: When True (default), always rebuild the PDF structure
                tree regardless of whether one already exists. Pass False to skip
                auto-tagging entirely (opt-out).
        """
        from . import pdf_remediator_fixes as fixes

        target = output_path or self.file_path
        results: List[RemediationResult] = []

        # 1. Metadata (title + language) ----------------------------------
        pdf_title = ""
        pdf_lang = "en"
        if report:
            pdf_title = getattr(report.document, "title", "") or ""
            pdf_lang = getattr(report.document, "language", "") or "en"
        generic_titles = {"", "Untitled", "untitled", "(anonymous)", "Unknown"}
        if not pdf_title or pdf_title.strip() in generic_titles:
            raw_name = Path(original_filename).stem if original_filename else "Document"
            pdf_title = raw_name.replace("+", " ").replace("-", " ").replace("_", " ").strip()

        meta_results = self.fix_metadata(title=pdf_title, language=pdf_lang)
        results.extend(meta_results)

        # 2. Run OCR (scanned pages check) first so subsequent steps work on a searchable PDF --------
        try:
            r = fixes.fix_scanned_pages(target)
            results.append(RemediationResult(
                issue_id=r["issue_id"],
                success=r["success"],
                message=r["message"],
                new_value=r.get("new_value", ""),
            ))
        except Exception as e:
            logger.error(f"fix_scanned_pages raised: {e}", exc_info=True)
            results.append(RemediationResult(
                issue_id="pdf-fix_scanned_pages",
                success=False,
                message=str(e),
            ))

        # 2b. Inject link annotations for plain text URLs so they exist before tagging
        try:
            r = fixes.inject_link_annotations(target)
            results.append(RemediationResult(
                issue_id=r["issue_id"],
                success=r["success"],
                message=r["message"],
                new_value=r.get("new_value", ""),
            ))
        except Exception as e:
            logger.error(f"inject_link_annotations raised: {e}", exc_info=True)
            results.append(RemediationResult(
                issue_id="pdf-inject-link-annots",
                success=False,
                message=str(e),
            ))

        # 3. Auto-tag PDFs -----------------------------------------------
        try:
            import pikepdf as _pk
            with _pk.open(str(target)) as _pdf:
                is_tagged = "/StructTreeRoot" in _pdf.Root
        except Exception:
            is_tagged = False

        from .config import settings

        # Always rebuild the structure tree unless the caller explicitly opts out
        # (overwrite_tags=False) or OpenDataLoader is disabled.
        should_tag = overwrite_tags and not settings.DISABLE_OPENDATALOADER
        if should_tag:
            reason = "rebuilding existing structure" if is_tagged else "untagged document"
            logger.info("Running PDF layout tagging using OpenDataLoader (%s)...", reason)
            tag_result = self.auto_tag_document(
                output_path=target,
                overwrite_tags=True,  # always overwrite since we decided to rebuild
                confidence_threshold=0.0,
            )
            if tag_result.get("success"):
                results.append(RemediationResult(
                    issue_id="pdf-auto-tag",
                    success=True,
                    message=(
                        f"Document tagging: created {tag_result['tags_created']} "
                        f"structure tags across {tag_result['pages_processed']} pages"
                    ),
                    new_value=str(tag_result.get("tag_counts", {})),
                ))
            else:
                results.append(RemediationResult(
                    issue_id="pdf-auto-tag",
                    success=False,
                    message=f"Auto-tagging failed: {tag_result.get('error', 'Unknown')}",
                ))
        elif not overwrite_tags:
            logger.info("PDF layout tagging skipped (opted out via overwrite_tags=False)")
            results.append(RemediationResult(
                issue_id="pdf-auto-tag",
                success=True,
                message="PDF auto-tagging skipped (opted out by request)",
            ))
        elif settings.DISABLE_OPENDATALOADER:
            logger.info("PDF layout tagging skipped (DISABLE_OPENDATALOADER is enabled)")
            results.append(RemediationResult(
                issue_id="pdf-auto-tag",
                success=False,
                message="PDF auto-tagging skipped (OpenDataLoader layout analysis disabled)",
            ))

        # 4-11. Structural / content fixes --------------------------------
        fix_funcs = [
            fixes.fix_content_stream_operator_states,
            fixes.fix_heading_hierarchy,
            fixes.fix_table_headers,
            fixes.fix_list_structure,
            fixes.fix_span_overuse,
            fixes.fix_reading_order,
            fixes.fix_untagged_urls,
            fixes.fix_bookmarks,
            fixes.fix_form_labels,
            fixes.fix_tab_order,
        ]
        for fn in fix_funcs:
            try:
                r = fn(target)
                results.append(RemediationResult(
                    issue_id=r["issue_id"],
                    success=r["success"],
                    message=r["message"],
                    new_value=r.get("new_value", ""),
                ))
            except Exception as e:
                logger.error(f"{fn.__name__} raised: {e}", exc_info=True)
                results.append(RemediationResult(
                    issue_id=f"pdf-{fn.__name__}",
                    success=False,
                    message=str(e),
                ))

        # 12. Finalize metadata LAST ---------------------------------------
        # The OCR rebuild (PyMuPDF) and the C++ tagging pass (QPDF) both drop
        # the XMP /Metadata stream, /ViewerPreferences and /Lang. Re-apply them
        # here, after every step that rewrites the file, so the PDF/UA + WCAG
        # 2.4.2 requirements survive: an XMP metadata stream containing dc:title,
        # and ViewerPreferences/DisplayDocTitle = true.
        try:
            import pikepdf as _pk
            with _pk.open(str(target), allow_overwriting_input=True) as pdf:
                # XMP metadata stream + dc:title (also synced into /Info via
                # update_docinfo). Creating the metadata context guarantees an
                # XMP packet is written on save.
                norm_lang = normalize_language_code(pdf_lang) if pdf_lang else "en"
                with pdf.open_metadata(set_pikepdf_as_editor=True, update_docinfo=True) as meta:
                    if pdf_title:
                        meta["dc:title"] = pdf_title
                    meta["dc:language"] = [norm_lang]

                pdf.Root.Lang = _pk.String(norm_lang)

                # DisplayDocTitle makes conforming viewers show the title rather
                # than the filename (required by PDF/UA, checked by PAC).
                if "/ViewerPreferences" not in pdf.Root:
                    pdf.Root.ViewerPreferences = _pk.Dictionary()
                pdf.Root.ViewerPreferences.DisplayDocTitle = True

                pdf.save()
            results.append(RemediationResult(
                issue_id="pdf-metadata-final",
                success=True,
                message="Finalized XMP metadata (dc:title), language, and DisplayDocTitle",
                new_value=pdf_title,
            ))
        except Exception as e:
            logger.error(f"finalize metadata raised: {e}", exc_info=True)
            results.append(RemediationResult(
                issue_id="pdf-metadata-final",
                success=False,
                message=str(e),
            ))

        return results

    def get_change_summary(self) -> Dict[str, Any]:
        """Get summary of changes made."""
        return {
            "total_changes": len(self.changes),
            "changes": self.changes
        }



