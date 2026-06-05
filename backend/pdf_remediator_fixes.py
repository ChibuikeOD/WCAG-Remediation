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
  - Tab order not set to S (2.4.3 / PDF/UA)
"""
import glob
import logging
import os
import re
import shutil
from pathlib import Path
from typing import List, Optional, Dict, Any

logger = logging.getLogger(__name__)


def _resolve_tessdata() -> Optional[str]:
    """Locate Tesseract's ``tessdata`` language folder for PyMuPDF.

    PyMuPDF/MuPDF expects the path to the ``tessdata`` directory *itself*
    (the folder containing ``eng.traineddata``), which differs from the
    classic Tesseract-CLI convention of pointing at the parent directory.
    We resolve it explicitly so OCR works regardless of how (or whether)
    ``TESSDATA_PREFIX`` was set on the host/container.

    Returns the tessdata directory path, or ``None`` if it cannot be found.
    """
    def _has_traineddata(d: str) -> bool:
        try:
            return bool(d) and os.path.isdir(d) and bool(glob.glob(os.path.join(d, "*.traineddata")))
        except Exception:
            return False

    # 1. Honour TESSDATA_PREFIX, accepting either the tessdata folder itself
    #    or its parent (classic Tesseract convention).
    env = os.environ.get("TESSDATA_PREFIX")
    if env:
        env = env.rstrip("/\\")
        if _has_traineddata(env):
            return env
        nested = os.path.join(env, "tessdata")
        if _has_traineddata(nested):
            return nested

    # 2. Common fixed locations across distros and Windows.
    candidates = [
        "/usr/share/tesseract-ocr/4.00/tessdata",
        "/usr/share/tesseract-ocr/5/tessdata",
        "/usr/share/tesseract-ocr/tessdata",
        "/usr/share/tessdata",
        "/usr/local/share/tessdata",
        r"C:\Program Files\Tesseract-OCR\tessdata",
        r"C:\Program Files (x86)\Tesseract-OCR\tessdata",
    ]
    # 3. Glob any versioned tesseract-ocr data dir we may have missed.
    candidates.extend(sorted(glob.glob("/usr/share/tesseract-ocr/*/tessdata"), reverse=True))

    for c in candidates:
        if _has_traineddata(c):
            return c

    # 4. Derive from the tesseract binary location, if present.
    binary = shutil.which("tesseract")
    if binary:
        bin_dir = os.path.dirname(os.path.realpath(binary))
        for rel in ("tessdata", os.path.join("..", "share", "tessdata"),
                    os.path.join("..", "share", "tesseract-ocr", "tessdata")):
            cand = os.path.normpath(os.path.join(bin_dir, rel))
            if _has_traineddata(cand):
                return cand

    return None

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
            pg_obj = None
            if hasattr(kid, "keys") and "/Pg" in kid:
                pg_obj = kid["/Pg"]
            elif hasattr(lst, "keys") and "/Pg" in lst:
                pg_obj = lst["/Pg"]

            lbody_dict = {
                "/Type": pikepdf.Name("/StructElem"),
                "/S": pikepdf.Name("/LBody"),
                "/P": pikepdf.Null(),   # will be updated below
                "/K": pikepdf.Array([kid]),
            }
            if pg_obj is not None:
                lbody_dict["/Pg"] = pg_obj
            lbody_ref = pdf.make_indirect(pikepdf.Dictionary(lbody_dict))

            li_dict = {
                "/Type": pikepdf.Name("/StructElem"),
                "/S": pikepdf.Name("/LI"),
                "/P": lst,
                "/K": pikepdf.Array([lbody_ref]),
            }
            if pg_obj is not None:
                li_dict["/Pg"] = pg_obj
            li_ref = pdf.make_indirect(pikepdf.Dictionary(li_dict))

            # Fix parent pointers now that both objects exist as indirect refs
            lbody_ref["/P"] = li_ref
            if hasattr(kid, "keys"):
                kid["/P"] = lbody_ref
            new_kids.append(li_ref)

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
    (top-to-bottom, then left-to-right) using the /A BBox attribute that the
    C++ engine embeds in each StructElem, falling back to MCID order."""
    if not HAS_PIKEPDF:
        return _result("pdf-reading-order", False, "pikepdf not available")

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

        def sort_key(elem):
            """Sort by page then by the BBox top-left corner embedded by C++ engine."""
            try:
                if not hasattr(elem, "keys"):
                    return (9999, 9999, 9999, 9999)

                # Page number as primary sort key
                pg = 0
                if "/Pg" in elem:
                    try:
                        pg_obj = elem["/Pg"]
                        pg = pdf.pages.index(pg_obj)
                    except Exception:
                        pg = 0

                # Use /A BBox (Layout attribute) written by the C++ engine
                if "/A" in elem:
                    attr = elem["/A"]
                    if hasattr(attr, "keys") and "/BBox" in attr:
                        bbox = attr["/BBox"]
                        if isinstance(bbox, pikepdf.Array) and len(bbox) == 4:
                            # PDF BBox: [left, bottom, right, top] (origin bottom-left)
                            # Sort top-to-bottom (descending y → ascending -top)
                            left  = float(bbox[0])
                            top   = float(bbox[3])
                            return (pg, -top, left, 0)

                # Fallback: use MCID (preserves content-stream order)
                mcid = _get_mcid(elem)
                return (pg, 9998, mcid if mcid is not None else 9999, 0)
            except Exception:
                return (9999, 9999, 9999, 9999)

        sorted_kids = sorted(list(kids), key=sort_key)
        doc_elem["/K"] = pikepdf.Array(sorted_kids)

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


def inject_link_annotations(pdf_path: Path) -> Dict[str, Any]:
    """Find URLs in page text and add /Link annotations for them."""
    if not HAS_PYMUPDF:
        return _result("pdf-inject-link-annots", False, "PyMuPDF not available")

    try:
        doc = fitz.open(str(pdf_path))
        added = 0
        for page_num, page in enumerate(doc):
            text = page.get_text("text")
            found_urls = URL_RE.findall(text)
            for url in found_urls:
                rects = page.search_for(url)
                for rect in rects:
                    # Check if there is already a link annot overlapping this rect
                    already_has = False
                    for link in page.get_links():
                        l_rect = fitz.Rect(link["from"])
                        if l_rect.intersects(rect):
                            already_has = True
                            break
                    if not already_has:
                        page.insert_link({
                            "kind": fitz.LINK_URI,
                            "from": rect,
                            "uri": url
                        })
                        added += 1
        if added > 0:
            doc.save(str(pdf_path), incremental=True, encryption=0)
        doc.close()
        return _result(
            "pdf-inject-link-annots", True,
            f"Injected {added} Link annotation(s) for URLs",
            f"{added} annotations injected"
        )
    except Exception as e:
        logger.error(f"inject_link_annotations: {e}", exc_info=True)
        return _result("pdf-inject-link-annots", False, str(e))


def fix_untagged_urls(pdf_path: Path) -> Dict[str, Any]:
    """Find URLs in page text and ensure they have both /Link annotations and structure elements."""
    if not HAS_PIKEPDF or not HAS_PYMUPDF:
        return _result("pdf-untagged-urls", False, "pikepdf/PyMuPDF not available")

    # 1. First, ensure all text URLs have /Link annotations on the pages
    try:
        inject_link_annotations(pdf_path)
    except Exception as e:
        logger.error(f"fix_untagged_urls - inject_link_annotations failed: {e}")

    # 2. Now check all /Link annotations across all pages to see if they are tagged
    try:
        pdf = pikepdf.open(str(pdf_path), allow_overwriting_input=True)
    except Exception as e:
        return _result("pdf-untagged-urls", False, str(e))

    try:
        if "/StructTreeRoot" not in pdf.Root:
            pdf.close()
            return _result("pdf-untagged-urls", True, "No structure tree; skipped")

        struct_root = pdf.Root["/StructTreeRoot"]
        
        # Build ParentTree map
        pt_map = {}
        if "/ParentTree" in struct_root:
            parent_tree = struct_root["/ParentTree"]
            if "/Nums" in parent_tree:
                nums = parent_tree["/Nums"]
                for i in range(0, len(nums), 2):
                    pt_map[int(nums[i])] = nums[i+1]
        
        # Find next parent tree key
        next_key = 0
        if pt_map:
            next_key = max(pt_map.keys()) + 1
        if "/ParentTreeNextKey" in struct_root:
            next_key = max(next_key, int(struct_root["/ParentTreeNextKey"]))

        doc_elem = _get_doc_element(pdf)
        if doc_elem is None:
            pdf.close()
            return _result("pdf-untagged-urls", True, "No document element; skipped")

        added = 0

        for page_num, page in enumerate(pdf.pages):
            annots = page.get("/Annots")
            if not annots:
                continue
            for annot in annots:
                if annot.get("/Subtype") == "/Link":
                    sp = annot.get("/StructParent")
                    # Check if it has a valid mapping in ParentTree to a /Link element
                    is_tagged = False
                    if sp is not None:
                        sp_val = int(sp)
                        if sp_val in pt_map:
                            mapped_obj = pt_map[sp_val]
                            if isinstance(mapped_obj, pikepdf.Dictionary) and mapped_obj.get("/S") == "/Link":
                                is_tagged = True
                    
                    if not is_tagged:
                        # Find or generate a StructParent key
                        if sp is None:
                            sp_val = next_key
                            next_key += 1
                            annot["/StructParent"] = sp_val
                        else:
                            sp_val = int(sp)

                        # Find a parent structure element. We attach to doc_elem.
                        link_elem = pdf.make_indirect(pikepdf.Dictionary({
                            "/Type": pikepdf.Name("/StructElem"),
                            "/S": pikepdf.Name("/Link"),
                            "/P": doc_elem,
                            "/Pg": page.obj,
                        }))
                        
                        # Add /OBJR to Kids of the Link structure element
                        objr = pikepdf.Dictionary({
                            "/Type": pikepdf.Name("/OBJR"),
                            "/Obj": annot,
                            "/Pg": page.obj,
                        })
                        link_elem["/K"] = pikepdf.Array([objr])
                        
                        # Append to doc_elem's kids
                        if "/K" not in doc_elem:
                            doc_elem["/K"] = pikepdf.Array()
                        if isinstance(doc_elem["/K"], pikepdf.Array):
                            doc_elem["/K"].append(link_elem)
                        elif isinstance(doc_elem["/K"], pikepdf.Dictionary):
                            # wrap it in an array
                            doc_elem["/K"] = pikepdf.Array([doc_elem["/K"], link_elem])
                            
                        # Add to the new ParentTree mappings
                        pt_map[sp_val] = link_elem
                        added += 1

        if added > 0:
            # Rebuild ParentTree Nums (with sorted keys!)
            parent_tree_nums = pikepdf.Array()
            for k in sorted(pt_map.keys()):
                parent_tree_nums.append(k)
                parent_tree_nums.append(pt_map[k])
            
            if "/ParentTree" not in struct_root:
                struct_root["/ParentTree"] = pdf.make_indirect(pikepdf.Dictionary())
            
            struct_root["/ParentTree"]["/Nums"] = parent_tree_nums
            struct_root["/ParentTreeNextKey"] = next_key
            pdf.save()

        pdf.close()
        return _result(
            "pdf-untagged-urls", True,
            f"Ensured all URLs are tagged as Links (added {added} Link tags)",
            f"{added} Link tags added",
        )
    except Exception as e:
        logger.error(f"fix_untagged_urls: {e}", exc_info=True)
        return _result("pdf-untagged-urls", False, str(e))
    finally:
        try:
            pdf.close()
        except Exception:
            pass


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
    if settings.DISABLE_OCR:
        return _result("pdf-ocr", False, "OCR skipped (OCR disabled on this server)")

    if not HAS_PYMUPDF:
        return _result("pdf-ocr", False, "PyMuPDF not available")

    tessdata = _resolve_tessdata()
    if not tessdata:
        return _result(
            "pdf-ocr", False,
            "OCR unavailable -- Tesseract language data (tessdata) not found. "
            "Install Tesseract OCR and ensure TESSDATA_PREFIX points to the "
            "'tessdata' folder for scanned-page remediation.",
        )

    try:
        doc = fitz.open(str(pdf_path))
        scanned_pages = []

        for page_num, page in enumerate(doc):
            # Check for non-embedded fonts or fonts with missing Unicode mapping
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

                        # 1. Flag if font is unnamed or bad
                        if not f_name or f_name == "n/a" or f_name == "":
                            has_bad_fonts = True
                            break

                        # 2. Flag if font is not embedded (PDF/UA violation) - REMOVED
                        # Triggering OCR for non-embedded fonts on text-heavy pages is destructive.

                        # 3. Flag if font is embedded but lacks ToUnicode map and uses non-standard encoding
                        dict_str = doc.xref_object(f_xref)
                        if "ToUnicode" not in dict_str:
                            clean_encoding = f_encoding.replace("/", "") if isinstance(f_encoding, str) else ""
                            standard_encodings = {"WinAnsiEncoding", "MacRomanEncoding", "MacExpertEncoding", "StandardEncoding", "PDFDocEncoding"}
                            if f_type == "Type0" or clean_encoding in ("Identity-H", "Identity-V") or (clean_encoding and clean_encoding not in standard_encodings):
                                has_bad_fonts = True
                                break
                if has_bad_fonts:
                    # Only run OCR if the page lacks significant extractable text
                    text = page.get_text("text").strip()
                    if len(text) < 100:
                        scanned_pages.append(page_num)
                        continue
            except Exception:
                pass

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

        # Reconstruct PDF to insert OCR text layer
        new_doc = fitz.open()
        ocr_done = 0
        last_error: Optional[str] = None
        for page_num in range(len(doc)):
            if page_num in scanned_pages:
                try:
                    page = doc[page_num]
                    # Render the scanned page to a high-quality image pixmap
                    pix = page.get_pixmap(dpi=150)
                    # Drop alpha channel if present, as OCR fails on transparent pixmaps
                    if pix.alpha:
                        pix = fitz.Pixmap(pix, 0)
                    # Run OCR and generate page bytes with the text layer. Pass the
                    # tessdata path explicitly so MuPDF locates the language data
                    # regardless of the TESSDATA_PREFIX convention on this host.
                    ocr_bytes = pix.pdfocr_tobytes(language="eng", tessdata=tessdata)
                    # Open the OCR-ed page and insert into new document
                    ocr_page_doc = fitz.open("pdf", ocr_bytes)
                    new_doc.insert_pdf(ocr_page_doc)
                    ocr_page_doc.close()
                    ocr_done += 1
                except Exception as e:
                    last_error = str(e)
                    logger.warning(f"OCR failed on page {page_num + 1}: {e}")
                    new_doc.insert_pdf(doc, from_page=page_num, to_page=page_num)
            else:
                new_doc.insert_pdf(doc, from_page=page_num, to_page=page_num)

        doc.close()

        if ocr_done:
            try:
                new_doc.set_toc(doc.get_toc())
            except Exception as e:
                logger.warning(f"Failed to copy TOC during OCR step: {e}")
            new_doc.save(str(pdf_path))
            new_doc.close()
            return _result(
                "pdf-ocr", True,
                f"Applied OCR to {ocr_done} scanned page(s)",
                f"{ocr_done} pages OCR'd",
            )
        else:
            new_doc.close()
            detail = f" (last error: {last_error})" if last_error else ""
            return _result(
                "pdf-ocr", False,
                f"OCR failed on all {len(scanned_pages)} scanned page(s) "
                f"using tessdata at '{tessdata}'.{detail}",
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


# ---------------------------------------------------------------------------
# 10. Tab order (PDF/UA clause 7.18.3 / WCAG 2.4.3)
# ---------------------------------------------------------------------------

def fix_tab_order(pdf_path: Path) -> Dict[str, Any]:
    """
    Set /Tabs /S on every page that contains annotations but is missing the
    entry or has it set to something other than /S.

    PDF/UA-1 §7.18.3 and PDF 1.7 §12.5 require /Tabs /S whenever a page has
    annotations so that assistive technology follows the logical reading order
    defined by the structure tree rather than arbitrary PDF object ordering.

    Related: WCAG 2.4.3 Focus Order (Level A)
    """
    if not HAS_PIKEPDF:
        return _result("pdf-tab-order", False, "pikepdf not available")

    try:
        pdf = pikepdf.open(str(pdf_path), allow_overwriting_input=True)
    except Exception as e:
        return _result("pdf-tab-order", False, str(e))

    try:
        fixed = 0
        for page in pdf.pages:
            # Only pages with a non-empty /Annots array need /Tabs /S
            if "/Annots" not in page:
                continue
            annots = page["/Annots"]
            if hasattr(annots, "__len__") and len(annots) == 0:
                continue

            tabs = page.get("/Tabs")
            if tabs is None or str(tabs) != "/S":
                page["/Tabs"] = pikepdf.Name("/S")
                fixed += 1

        if fixed:
            pdf.save()
            return _result(
                "pdf-tab-order", True,
                f"Set /Tabs /S on {fixed} page(s) with annotations",
                f"{fixed} pages fixed",
            )
        return _result("pdf-tab-order", True, "Tab order already correct on all pages")
    except Exception as e:
        logger.error(f"fix_tab_order: {e}", exc_info=True)
        return _result("pdf-tab-order", False, str(e))
    finally:
        pdf.close()


def resolve_pdf_alt_texts(pdf_path: Path, resolutions: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Applies user-provided alt-text resolutions to a PDF document's structure tree.
    """
    if not HAS_PIKEPDF:
        return _result("pdf-alt-text", False, "pikepdf not available")

    try:
        pdf = pikepdf.open(str(pdf_path), allow_overwriting_input=True)
    except Exception as e:
        return _result("pdf-alt-text", False, str(e))

    try:
        if "/StructTreeRoot" not in pdf.Root:
            return _result("pdf-alt-text", False, "Document has no structure tree")

        struct_root = pdf.Root["/StructTreeRoot"]
        fixed = 0

        for res in resolutions:
            img_id = res["id"]
            alt_text = res["alt_text"]
            is_decorative = res.get("is_decorative", False)

            # Skip images not matching PDF struct path format
            if "-" not in img_id and not img_id.isdigit():
                continue

            try:
                path = [int(x) for x in img_id.split("-")]
            except ValueError:
                continue

            # Traverse to the target node
            node = struct_root
            success = True
            for idx in path:
                if "/K" not in node:
                    success = False
                    break
                kids = node["/K"]
                if not isinstance(kids, pikepdf.Array):
                    kids = [kids]
                if idx >= len(kids):
                    success = False
                    break
                node = kids[idx]

            if success and hasattr(node, "keys"):
                if is_decorative:
                    node["/Alt"] = pikepdf.String("")
                else:
                    node["/Alt"] = pikepdf.String(alt_text)
                fixed += 1

        if fixed > 0:
            pdf.save()
            return _result(
                "pdf-alt-text", True,
                f"Resolved alt-text for {fixed} figure(s)",
                f"{fixed} figure alt-texts updated",
            )
        return _result("pdf-alt-text", True, "No figure alt-texts were updated")
    except Exception as e:
        logger.error(f"resolve_pdf_alt_texts: {e}", exc_info=True)
        return _result("pdf-alt-text", False, str(e))
    finally:
        pdf.close()

