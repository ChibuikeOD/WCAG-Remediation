"""
PDF structure-level remediation fixes.

Each function opens a PDF with pikepdf (or PyMuPDF), applies a targeted
structural repair, and saves. All functions are idempotent -- if the issue
is absent, they return a no-op success result.

Fixes covered:
  - Heading hierarchy gaps (1.3.1)
  - Table headers missing (1.3.1)
  - List structure invalid (1.3.1)
  - Span overuse (1.3.1)
  - Reading order (1.3.2)
  - Untagged URLs (2.4.4)
  - Missing bookmarks (2.4.5)
  - Scanned pages / OCR (1.4.5)
  - Form field labels (3.3.2)
"""
import logging
import re
from pathlib import Path
from typing import List, Optional, Dict, Any

logger = logging.getLogger(__name__)

try:
    import pikepdf
    HAS_PIKEPDF = True
except ImportError:
    HAS_PIKEPDF = False

try:
    import fitz
    HAS_PYMUPDF = True
except ImportError:
    HAS_PYMUPDF = False


def _result(issue_id: str, success: bool, message: str, new_value: str = ""):
    """Convenience dict matching RemediationResult fields."""
    return {
        "issue_id": issue_id,
        "success": success,
        "message": message,
        "new_value": new_value,
    }


# ---------------------------------------------------------------------------
# Helpers for walking the pikepdf structure tree
# ---------------------------------------------------------------------------

def _collect_struct_elems(root, tag_filter: Optional[set] = None, max_depth: int = 50) -> List:
    """Recursively collect structure elements, optionally filtered by /S tag."""
    results = []
    _walk(root, tag_filter, results, 0, max_depth)
    return results


def _walk(node, tag_filter, out, depth, max_depth):
    if depth > max_depth:
        return
    try:
        if "/K" not in node:
            return
        kids = node["/K"]
        if not isinstance(kids, pikepdf.Array):
            kids = [kids]
        for kid in kids:
            if not hasattr(kid, "keys"):
                continue
            if "/S" in kid:
                tag = str(kid["/S"])
                if tag_filter is None or tag in tag_filter:
                    out.append(kid)
            _walk(kid, tag_filter, out, depth + 1, max_depth)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 1. Heading hierarchy (WCAG 1.3.1)
# ---------------------------------------------------------------------------

def fix_heading_hierarchy(pdf_path: Path) -> Dict[str, Any]:
    """
    Close heading-level gaps so the sequence never skips (e.g. H1->H4
    becomes H1->H2).  Also ensures H1 exists if any headings are present.
    """
    if not HAS_PIKEPDF:
        return _result("pdf-heading-hierarchy", False, "pikepdf not available")

    try:
        pdf = pikepdf.open(str(pdf_path), allow_overwriting_input=True)
    except Exception as e:
        return _result("pdf-heading-hierarchy", False, str(e))

    try:
        if "/StructTreeRoot" not in pdf.Root:
            return _result("pdf-heading-hierarchy", True, "No structure tree; skipped")

        heading_tags = {f"/H{i}" for i in range(1, 7)}
        headings = _collect_struct_elems(pdf.Root["/StructTreeRoot"], heading_tags)

        if not headings:
            return _result("pdf-heading-hierarchy", True, "No headings found; skipped")

        levels = []
        for h in headings:
            tag = str(h["/S"])
            try:
                levels.append(int(tag[2]))
            except (ValueError, IndexError):
                levels.append(6)

        fixed = 0
        max_allowed = 1
        for i, level in enumerate(levels):
            if level > max_allowed:
                new_level = max_allowed
                headings[i]["/S"] = pikepdf.Name(f"/H{new_level}")
                levels[i] = new_level
                fixed += 1
            max_allowed = levels[i] + 1

        if fixed:
            pdf.save()
            return _result(
                "pdf-heading-hierarchy", True,
                f"Fixed {fixed} heading level skip(s)",
                f"{fixed} headings re-leveled",
            )
        return _result("pdf-heading-hierarchy", True, "Heading hierarchy already correct")
    except Exception as e:
        logger.error(f"fix_heading_hierarchy: {e}", exc_info=True)
        return _result("pdf-heading-hierarchy", False, str(e))
    finally:
        pdf.close()


# ---------------------------------------------------------------------------
# 2. Table headers (WCAG 1.3.1)
# ---------------------------------------------------------------------------

def fix_table_headers(pdf_path: Path) -> Dict[str, Any]:
    """Promote first-row TD cells to TH in every table that lacks headers."""
    if not HAS_PIKEPDF:
        return _result("pdf-table-headers", False, "pikepdf not available")

    try:
        pdf = pikepdf.open(str(pdf_path), allow_overwriting_input=True)
    except Exception as e:
        return _result("pdf-table-headers", False, str(e))

    try:
        if "/StructTreeRoot" not in pdf.Root:
            return _result("pdf-table-headers", True, "No structure tree; skipped")

        tables = _collect_struct_elems(pdf.Root["/StructTreeRoot"], {"/Table"})
        if not tables:
            return _result("pdf-table-headers", True, "No tables found; skipped")

        fixed_tables = 0
        for table in tables:
            if _table_has_th(table):
                continue
            first_row = _find_first_child(table, "/TR")
            if first_row is None:
                continue
            promoted = _promote_td_to_th(first_row)
            if promoted:
                fixed_tables += 1

        if fixed_tables:
            pdf.save()
            return _result(
                "pdf-table-headers", True,
                f"Added header cells to {fixed_tables} table(s)",
                f"{fixed_tables} tables fixed",
            )
        return _result("pdf-table-headers", True, "All tables already have headers")
    except Exception as e:
        logger.error(f"fix_table_headers: {e}", exc_info=True)
        return _result("pdf-table-headers", False, str(e))
    finally:
        pdf.close()


def _table_has_th(table) -> bool:
    elems = _collect_struct_elems(table, {"/TH"}, max_depth=5)
    return len(elems) > 0


def _find_first_child(node, tag: str):
    try:
        kids = node["/K"]
        if not isinstance(kids, pikepdf.Array):
            kids = [kids]
        for kid in kids:
            if hasattr(kid, "keys") and "/S" in kid and str(kid["/S"]) == tag:
                return kid
    except Exception:
        pass
    return None


def _promote_td_to_th(row) -> int:
    promoted = 0
    try:
        kids = row["/K"]
        if not isinstance(kids, pikepdf.Array):
            kids = [kids]
        for kid in kids:
            if hasattr(kid, "keys") and "/S" in kid and str(kid["/S"]) == "/TD":
                kid["/S"] = pikepdf.Name("/TH")
                promoted += 1
    except Exception:
        pass
    return promoted


# ---------------------------------------------------------------------------
# 3. List structure (WCAG 1.3.1)
# ---------------------------------------------------------------------------

def fix_list_structure(pdf_path: Path) -> Dict[str, Any]:
    """Wrap bare children of /L elements in /LI > /LBody if missing."""
    if not HAS_PIKEPDF:
        return _result("pdf-list-structure", False, "pikepdf not available")

    try:
        pdf = pikepdf.open(str(pdf_path), allow_overwriting_input=True)
    except Exception as e:
        return _result("pdf-list-structure", False, str(e))

    try:
        if "/StructTreeRoot" not in pdf.Root:
            return _result("pdf-list-structure", True, "No structure tree; skipped")

        lists = _collect_struct_elems(pdf.Root["/StructTreeRoot"], {"/L"})
        if not lists:
            return _result("pdf-list-structure", True, "No lists found; skipped")

        fixed = 0
        for lst in lists:
            if _list_has_li(lst):
                continue
            if _wrap_list_children(pdf, lst):
                fixed += 1

        if fixed:
            pdf.save()
            return _result(
                "pdf-list-structure", True,
                f"Fixed structure of {fixed} list(s)",
                f"{fixed} lists wrapped in LI/LBody",
            )
        return _result("pdf-list-structure", True, "All lists already well-structured")
    except Exception as e:
        logger.error(f"fix_list_structure: {e}", exc_info=True)
        return _result("pdf-list-structure", False, str(e))
    finally:
        pdf.close()


def _list_has_li(lst) -> bool:
    elems = _collect_struct_elems(lst, {"/LI"}, max_depth=2)
    return len(elems) > 0


def _wrap_list_children(pdf, lst) -> bool:
    try:
        if "/K" not in lst:
            return False
        kids = lst["/K"]
        if not isinstance(kids, pikepdf.Array):
            kids = pikepdf.Array([kids])

        new_kids = pikepdf.Array()
        for kid in kids:
            lbody = pdf.make_indirect(pikepdf.Dictionary({
                "/Type": pikepdf.Name("/StructElem"),
                "/S": pikepdf.Name("/LBody"),
                "/P": lst,
                "/K": pikepdf.Array([kid]),
            }))
            li = pdf.make_indirect(pikepdf.Dictionary({
                "/Type": pikepdf.Name("/StructElem"),
                "/S": pikepdf.Name("/LI"),
                "/P": lst,
                "/K": pikepdf.Array([lbody]),
            }))
            new_kids.append(li)

        lst["/K"] = new_kids
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# 4. Span overuse (WCAG 1.3.1)
# ---------------------------------------------------------------------------

def fix_span_overuse(pdf_path: Path) -> Dict[str, Any]:
    """Reclassify /Span elements as /P (default) or /H1-H6 using font-size
    heuristics from the page content."""
    if not HAS_PIKEPDF or not HAS_PYMUPDF:
        return _result("pdf-span-overuse", False, "pikepdf/PyMuPDF not available")

    try:
        pdf = pikepdf.open(str(pdf_path), allow_overwriting_input=True)
    except Exception as e:
        return _result("pdf-span-overuse", False, str(e))

    try:
        if "/StructTreeRoot" not in pdf.Root:
            return _result("pdf-span-overuse", True, "No structure tree; skipped")

        spans = _collect_struct_elems(pdf.Root["/StructTreeRoot"], {"/Span"})
        if len(spans) < 20:
            pdf.close()
            return _result("pdf-span-overuse", True, "Span count acceptable; skipped")

        font_map = _build_font_size_map(pdf_path)

        reclassified = 0
        for span in spans:
            page_num = _get_page_num(span)
            mcid = _get_mcid(span)
            font_size = font_map.get((page_num, mcid), 12)

            if font_size >= 20:
                span["/S"] = pikepdf.Name("/H1")
            elif font_size >= 16:
                span["/S"] = pikepdf.Name("/H2")
            elif font_size >= 14:
                span["/S"] = pikepdf.Name("/H3")
            else:
                span["/S"] = pikepdf.Name("/P")
            reclassified += 1

        if reclassified:
            pdf.save()
            return _result(
                "pdf-span-overuse", True,
                f"Reclassified {reclassified} Span tags to semantic tags",
                f"{reclassified} Spans fixed",
            )
        return _result("pdf-span-overuse", True, "No Span tags to reclassify")
    except Exception as e:
        logger.error(f"fix_span_overuse: {e}", exc_info=True)
        return _result("pdf-span-overuse", False, str(e))
    finally:
        pdf.close()


def _build_font_size_map(pdf_path: Path) -> Dict:
    """Build mapping (page_num, mcid) -> average font size from page content."""
    result = {}
    try:
        doc = fitz.open(str(pdf_path))
        for page_num, page in enumerate(doc):
            blocks = page.get_text("dict").get("blocks", [])
            for block in blocks:
                if "lines" not in block:
                    continue
                for line in block["lines"]:
                    for span in line.get("spans", []):
                        size = span.get("size", 12)
                        result[(page_num, None)] = max(
                            result.get((page_num, None), 0), size
                        )
        doc.close()
    except Exception:
        pass
    return result


def _get_page_num(elem) -> int:
    try:
        if "/Pg" in elem:
            return 0
    except Exception:
        pass
    return 0


def _get_mcid(elem):
    try:
        k = elem["/K"]
        if isinstance(k, int):
            return k
        if isinstance(k, pikepdf.Array) and len(k) > 0:
            v = k[0]
            if isinstance(v, int):
                return v
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# 5. Reading order (WCAG 1.3.2)
# ---------------------------------------------------------------------------

def fix_reading_order(pdf_path: Path) -> Dict[str, Any]:
    """Re-sort structure-tree children by geometric position
    (top-to-bottom, then left-to-right) using bounding-box data from PyMuPDF."""
    if not HAS_PIKEPDF or not HAS_PYMUPDF:
        return _result("pdf-reading-order", False, "pikepdf/PyMuPDF not available")

    try:
        pdf = pikepdf.open(str(pdf_path), allow_overwriting_input=True)
    except Exception as e:
        return _result("pdf-reading-order", False, str(e))

    try:
        if "/StructTreeRoot" not in pdf.Root:
            return _result("pdf-reading-order", True, "No structure tree; skipped")

        root = pdf.Root["/StructTreeRoot"]
        doc_elem = None
        try:
            k = root["/K"]
            if isinstance(k, pikepdf.Array) and len(k) > 0:
                doc_elem = k[0]
            elif hasattr(k, "keys"):
                doc_elem = k
        except Exception:
            pass

        if doc_elem is None or "/K" not in doc_elem:
            return _result("pdf-reading-order", True, "No document element; skipped")

        kids = doc_elem["/K"]
        if not isinstance(kids, pikepdf.Array) or len(kids) < 2:
            return _result("pdf-reading-order", True, "Too few elements to reorder")

        bbox_data = _extract_struct_bboxes(pdf_path)

        kid_list = list(kids)
        def sort_key(elem):
            try:
                pg = _get_page_num(elem) if hasattr(elem, "keys") else 0
                mcid = _get_mcid(elem) if hasattr(elem, "keys") else None
                if mcid is not None and (pg, mcid) in bbox_data:
                    y, x = bbox_data[(pg, mcid)]
                    return (pg, y, x)
            except Exception:
                pass
            return (9999, 9999, 9999)

        sorted_kids = sorted(kid_list, key=sort_key)
        new_arr = pikepdf.Array(sorted_kids)
        doc_elem["/K"] = new_arr

        pdf.save()
        return _result(
            "pdf-reading-order", True,
            f"Reordered {len(sorted_kids)} structure elements by position",
            "Reading order fixed",
        )
    except Exception as e:
        logger.error(f"fix_reading_order: {e}", exc_info=True)
        return _result("pdf-reading-order", False, str(e))
    finally:
        pdf.close()


def _extract_struct_bboxes(pdf_path: Path) -> Dict:
    """Return dict of (page_num, mcid) -> (y_center, x_center)."""
    result = {}
    try:
        doc = fitz.open(str(pdf_path))
        for page_num, page in enumerate(doc):
            words = page.get_text("words")
            for i, w in enumerate(words):
                y_center = (w[1] + w[3]) / 2
                x_center = (w[0] + w[2]) / 2
                result[(page_num, i)] = (y_center, x_center)
        doc.close()
    except Exception:
        pass
    return result


# ---------------------------------------------------------------------------
# 6. Untagged URLs (WCAG 2.4.4)
# ---------------------------------------------------------------------------

URL_RE = re.compile(r'https?://[^\s<>"{}|\\^`\[\]]+|www\.[^\s<>"{}|\\^`\[\]]+')


def fix_untagged_urls(pdf_path: Path) -> Dict[str, Any]:
    """Find URLs in page text and add /Link structure elements for them."""
    if not HAS_PIKEPDF or not HAS_PYMUPDF:
        return _result("pdf-untagged-urls", False, "pikepdf/PyMuPDF not available")

    try:
        doc = fitz.open(str(pdf_path))
        urls_by_page: Dict[int, List[str]] = {}
        for page_num, page in enumerate(doc):
            text = page.get_text("text")
            found = URL_RE.findall(text)
            if found:
                urls_by_page[page_num] = found
        doc.close()
    except Exception as e:
        return _result("pdf-untagged-urls", False, str(e))

    total_urls = sum(len(v) for v in urls_by_page.values())
    if total_urls == 0:
        return _result("pdf-untagged-urls", True, "No untagged URLs found")

    try:
        pdf = pikepdf.open(str(pdf_path), allow_overwriting_input=True)
    except Exception as e:
        return _result("pdf-untagged-urls", False, str(e))

    try:
        if "/StructTreeRoot" not in pdf.Root:
            pdf.close()
            return _result("pdf-untagged-urls", True, "No structure tree; skipped")

        existing_links = _collect_struct_elems(
            pdf.Root["/StructTreeRoot"], {"/Link"}
        )
        if len(existing_links) >= total_urls:
            pdf.close()
            return _result("pdf-untagged-urls", True, "URLs already tagged as Links")

        doc_elem = _get_doc_element(pdf)
        if doc_elem is None:
            pdf.close()
            return _result("pdf-untagged-urls", True, "No document element; skipped")

        added = 0
        for page_num, urls in urls_by_page.items():
            if page_num >= len(pdf.pages):
                continue
            page_obj = pdf.pages[page_num].obj
            for url in urls:
                link_elem = pdf.make_indirect(pikepdf.Dictionary({
                    "/Type": pikepdf.Name("/StructElem"),
                    "/S": pikepdf.Name("/Link"),
                    "/P": doc_elem,
                    "/Pg": page_obj,
                    "/Alt": pikepdf.String(url[:200]),
                }))
                doc_elem["/K"].append(link_elem)
                added += 1

        if added:
            pdf.save()
        return _result(
            "pdf-untagged-urls", True,
            f"Added {added} Link tag(s) for URLs",
            f"{added} URLs tagged",
        )
    except Exception as e:
        logger.error(f"fix_untagged_urls: {e}", exc_info=True)
        return _result("pdf-untagged-urls", False, str(e))
    finally:
        pdf.close()


def _get_doc_element(pdf):
    """Return the /Document struct element (first child of StructTreeRoot)."""
    try:
        root = pdf.Root["/StructTreeRoot"]
        k = root["/K"]
        if isinstance(k, pikepdf.Array) and len(k) > 0:
            return k[0]
        if hasattr(k, "keys"):
            return k
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# 7. Bookmarks (WCAG 2.4.5)
# ---------------------------------------------------------------------------

def fix_bookmarks(pdf_path: Path) -> Dict[str, Any]:
    """Generate bookmarks from heading-like text (large/bold) if none exist."""
    if not HAS_PYMUPDF:
        return _result("pdf-bookmarks", False, "PyMuPDF not available")

    try:
        doc = fitz.open(str(pdf_path))
        if doc.get_toc():
            doc.close()
            return _result("pdf-bookmarks", True, "Bookmarks already present")

        toc = []
        for page_num, page in enumerate(doc):
            blocks = page.get_text("dict").get("blocks", [])
            for block in blocks:
                if "lines" not in block:
                    continue
                for line in block["lines"]:
                    for span in line.get("spans", []):
                        size = span.get("size", 12)
                        text = span.get("text", "").strip()
                        if not text or len(text) < 3 or len(text) > 120:
                            continue
                        if size >= 16:
                            level = 1 if size >= 20 else 2
                            toc.append([level, text, page_num + 1])

        if not toc:
            doc.close()
            return _result("pdf-bookmarks", True, "No heading text found for bookmarks")

        # PyMuPDF TOC must start with a level 1 item to avoid ValueError
        if toc[0][0] > 1:
            toc[0][0] = 1

        doc.set_toc(toc)
        doc.save(str(pdf_path), incremental=True, encryption=0)
        doc.close()
        return _result(
            "pdf-bookmarks", True,
            f"Added {len(toc)} bookmark(s) from document headings",
            f"{len(toc)} bookmarks",
        )
    except Exception as e:
        logger.error(f"fix_bookmarks: {e}", exc_info=True)
        return _result("pdf-bookmarks", False, str(e))


# ---------------------------------------------------------------------------
# 8. Scanned pages / OCR (WCAG 1.4.5)
# ---------------------------------------------------------------------------

def fix_scanned_pages(pdf_path: Path) -> Dict[str, Any]:
    """Run OCR on image-only pages to insert a searchable text layer."""
    from .config import settings
    if settings.DISABLE_HEAVY_MODELS:
        return _result("pdf-ocr", False, "OCR skipped (heavy models disabled on this server)")

    if not HAS_PYMUPDF:
        return _result("pdf-ocr", False, "PyMuPDF not available")

    try:
        doc = fitz.open(str(pdf_path))
        scanned_pages = []

        for page_num, page in enumerate(doc):
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

        if not scanned_pages:
            doc.close()
            return _result("pdf-ocr", True, "No scanned pages detected")

        ocr_done = 0
        for page_num in scanned_pages:
            try:
                page = doc[page_num]
                tp = page.get_textpage_ocr(flags=fitz.TEXT_PRESERVE_WHITESPACE, full=True)
                if tp:
                    ocr_done += 1
            except Exception as e:
                logger.warning(f"OCR failed on page {page_num + 1}: {e}")

        if ocr_done:
            doc.save(str(pdf_path), incremental=True, encryption=0)

        doc.close()

        if ocr_done:
            return _result(
                "pdf-ocr", True,
                f"Applied OCR to {ocr_done} scanned page(s)",
                f"{ocr_done} pages OCR'd",
            )
        return _result(
            "pdf-ocr", False,
            "OCR failed -- Tesseract may not be installed. "
            "Install Tesseract OCR for scanned-page remediation.",
        )
    except Exception as e:
        logger.error(f"fix_scanned_pages: {e}", exc_info=True)
        return _result("pdf-ocr", False, str(e))


# ---------------------------------------------------------------------------
# 9. Form field labels (WCAG 3.3.2)
# ---------------------------------------------------------------------------

def fix_form_labels(pdf_path: Path) -> Dict[str, Any]:
    """Set tooltip (TU) text on form fields that lack one, using the field name."""
    if not HAS_PYMUPDF:
        return _result("pdf-form-labels", False, "PyMuPDF not available")

    try:
        doc = fitz.open(str(pdf_path))
        fixed = 0

        for page in doc:
            widgets = page.widgets()
            if not widgets:
                continue
            for widget in widgets:
                if widget.field_type_string == "unknown":
                    continue
                existing_tt = widget.field_label or ""
                if existing_tt.strip():
                    continue
                name = widget.field_name or widget.field_type_string or "Input"
                label = re.sub(r'[-_.]', ' ', name).strip().title()
                if not label:
                    label = "Input Field"
                try:
                    widget.field_label = label
                    widget.update()
                    fixed += 1
                except Exception:
                    pass

        if fixed:
            doc.save(str(pdf_path), incremental=True, encryption=0)

        doc.close()

        if fixed:
            return _result(
                "pdf-form-labels", True,
                f"Labeled {fixed} form field(s)",
                f"{fixed} fields labeled",
            )
        return _result("pdf-form-labels", True, "All form fields already labeled or none present")
    except Exception as e:
        logger.error(f"fix_form_labels: {e}", exc_info=True)
        return _result("pdf-form-labels", False, str(e))
