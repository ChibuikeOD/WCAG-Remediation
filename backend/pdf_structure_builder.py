"""
PDF structure tree builder.

Creates a document-level structure tree from provider-neutral layout blocks.
The structure writer remains intentionally simple: it emits one /StructElem per
detected block and can replace an existing tree when overwrite is requested.
"""
import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    import pikepdf
    HAS_PIKEPDF = True
except ImportError:
    HAS_PIKEPDF = False

from .layout_model import DocumentLayoutAnalyzer, PageLayout


TAG_TO_PDF_NAME = {
    "H1": "/H1",
    "H2": "/H2",
    "H3": "/H3",
    "H4": "/H4",
    "H5": "/H5",
    "H6": "/H6",
    "P": "/P",
    "L": "/L",
    "LI": "/LI",
    "Table": "/Table",
    "Figure": "/Figure",
    "Caption": "/Caption",
    "Note": "/Note",
    "Formula": "/Formula",
    "Span": "/Span",
}


@dataclass
class TaggingResult:
    """Result of the PDF tagging operation."""

    success: bool
    output_path: Optional[Path] = None
    total_pages: int = 0
    total_tags_created: int = 0
    tag_counts: Dict[str, int] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


class PDFStructureBuilder:
    """Build a tagged PDF from provider-neutral layout analysis results."""

    def __init__(self):
        if not HAS_PIKEPDF:
            raise RuntimeError("pikepdf is required for PDF structure building")

    def build_tagged_pdf(
        self,
        source_path: Path,
        output_path: Path,
        layouts: List[PageLayout],
        overwrite_existing_tags: bool = False,
    ) -> TaggingResult:
        """Create a tagged copy of the source PDF using detected layout blocks."""
        result = TaggingResult(success=False, output_path=output_path)

        try:
            if source_path.resolve() != output_path.resolve():
                output_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_path, output_path)

            self._build_tagged_structure(
                output_path,
                layouts,
                result,
                overwrite_existing_tags=overwrite_existing_tags,
            )

            result.success = True
            result.total_pages = len(layouts)
            logger.info(
                "Tagged PDF created: %s tags across %s pages",
                result.total_tags_created,
                result.total_pages,
            )
        except Exception as exc:
            logger.error("PDF tagging failed: %s", exc, exc_info=True)
            result.errors.append(str(exc))

        return result

    @staticmethod
    def _clear_existing_structure_tags(pdf: "pikepdf.Pdf") -> None:
        """Remove the current structure tree and related page references."""
        if "/StructTreeRoot" in pdf.Root:
            old_tree = pdf.Root["/StructTreeRoot"]
            if hasattr(old_tree, "keys"):
                if "/K" in old_tree:
                    old_tree["/K"] = pikepdf.Array()
                if "/ParentTree" in old_tree:
                    del old_tree["/ParentTree"]
                if "/ParentTreeNextKey" in old_tree:
                    del old_tree["/ParentTreeNextKey"]
            del pdf.Root["/StructTreeRoot"]

        if "/MarkInfo" in pdf.Root:
            del pdf.Root["/MarkInfo"]

        for page in pdf.pages:
            if "/StructParents" in page.obj:
                del page.obj["/StructParents"]

    def _build_tagged_structure(
        self,
        pdf_path: Path,
        layouts: List[PageLayout],
        result: TaggingResult,
        overwrite_existing_tags: bool = False,
    ) -> None:
        """Build the full tagged structure in a single pikepdf session."""
        pdf = pikepdf.open(str(pdf_path), allow_overwriting_input=True)

        try:
            if overwrite_existing_tags:
                self._clear_existing_structure_tags(pdf)

            page_counters: Dict[int, int] = {}
            block_entries: List[Dict[str, Any]] = []

            for layout in layouts:
                if layout.page_number >= len(pdf.pages):
                    result.warnings.append(f"Page {layout.page_number} out of range")
                    continue

                for block in layout.blocks:
                    if block.tag == "Artifact":
                        continue

                    page_num = layout.page_number
                    mcid = page_counters.get(page_num, 0)
                    page_counters[page_num] = mcid + 1
                    block_entries.append(
                        {
                            "mcid": mcid,
                            "tag": block.tag,
                            "text": block.text,
                            "page_num": page_num,
                            "raw_bbox": block.metadata.get("raw_bbox"),
                        }
                    )

            if not block_entries:
                result.warnings.append("No taggable content blocks found")
                return

            parent_tree_nums = pikepdf.Array()
            parent_tree_arrays: Dict[int, Any] = {}

            doc_elem_kids = pikepdf.Array()
            doc_elem = pdf.make_indirect(
                pikepdf.Dictionary(
                    {
                        "/Type": pikepdf.Name("/StructElem"),
                        "/S": pikepdf.Name("/Document"),
                        "/K": doc_elem_kids,
                    }
                )
            )

            for entry in block_entries:
                tag = entry["tag"]
                text = entry["text"]
                page_num = entry["page_num"]
                mcid = entry["mcid"]
                raw_bbox = entry.get("raw_bbox")

                struct_type_name = TAG_TO_PDF_NAME.get(tag, "/Span")
                page_obj = pdf.pages[page_num].obj

                se_dict = pikepdf.Dictionary(
                    {
                        "/Type": pikepdf.Name("/StructElem"),
                        "/S": pikepdf.Name(struct_type_name),
                        "/P": doc_elem,
                        "/K": pikepdf.Array([mcid]),
                        "/Pg": page_obj,
                    }
                )

                if raw_bbox and len(raw_bbox) == 4:
                    left, bottom, right, top = raw_bbox
                    bbox_array = pikepdf.Array([left, bottom, right, top])
                    attr_dict = pikepdf.Dictionary({
                        "/O": pikepdf.Name("/Layout"),
                        "/BBox": bbox_array
                    })
                    se_dict["/A"] = attr_dict

                if tag == "Figure":
                    se_dict["/Alt"] = pikepdf.String("[Image requires alt text]")

                if text and tag in {"H1", "H2", "H3", "H4", "H5", "H6", "Caption"}:
                    se_dict["/T"] = pikepdf.String(text[:200])

                se_ref = pdf.make_indirect(se_dict)
                doc_elem_kids.append(se_ref)

                if page_num not in parent_tree_arrays:
                    parent_tree_arrays[page_num] = pikepdf.Array()
                parent_tree_arrays[page_num].append(se_ref)

                result.tag_counts[tag] = result.tag_counts.get(tag, 0) + 1

            result.total_tags_created = len(block_entries)

            for page_num in sorted(parent_tree_arrays):
                refs = pdf.make_indirect(parent_tree_arrays[page_num])
                parent_tree_nums.append(page_num)
                parent_tree_nums.append(refs)

            parent_tree = pdf.make_indirect(pikepdf.Dictionary({"/Nums": parent_tree_nums}))

            struct_tree_root = pdf.make_indirect(
                pikepdf.Dictionary(
                    {
                        "/Type": pikepdf.Name("/StructTreeRoot"),
                        "/K": pikepdf.Array([doc_elem]),
                        "/ParentTree": parent_tree,
                        "/ParentTreeNextKey": len(parent_tree_arrays),
                    }
                )
            )

            doc_elem["/P"] = struct_tree_root

            pdf.Root["/StructTreeRoot"] = struct_tree_root
            pdf.Root["/MarkInfo"] = pikepdf.Dictionary({"/Marked": True})
            if "/Lang" not in pdf.Root:
                pdf.Root["/Lang"] = pikepdf.String("en")

            for page_num in parent_tree_arrays:
                pdf.pages[page_num].obj["/StructParents"] = page_num

            pdf.save()
            logger.info(
                "Structure tree built: %s elements, %s pages tagged",
                len(block_entries),
                len(parent_tree_arrays),
            )
        finally:
            pdf.close()


def build_tagged_pdf(
    source_path: Path,
    output_path: Path,
    model_path: str = "",
    confidence_threshold: float = 0.0,
    overwrite_existing_tags: bool = False,
) -> TaggingResult:
    """
    Convenience helper: analyze a PDF and produce a tagged copy.

    Uses the fine-tuned LayoutLMv3 model in ``layoutLM_trained`` by default.
    """
    analyzer = DocumentLayoutAnalyzer(
        model_path=model_path,
        confidence_threshold=confidence_threshold,
    )
    layouts = analyzer.analyze_document(source_path)

    builder = PDFStructureBuilder()
    return builder.build_tagged_pdf(
        source_path,
        output_path,
        layouts,
        overwrite_existing_tags=overwrite_existing_tags,
    )
