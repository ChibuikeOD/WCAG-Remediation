"""
Shared PDF auto-tagging service backed by OpenDataLoader extraction.
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

try:
    import pikepdf
    HAS_PIKEPDF = True
except ImportError:
    HAS_PIKEPDF = False

from .layout_model import DocumentLayoutAnalyzer
from .pdf_structure_builder import PDFStructureBuilder


def _has_structure_tree(pdf_path: Path) -> bool:
    if not HAS_PIKEPDF:
        return False

    with pikepdf.open(str(pdf_path)) as pdf:
        return "/StructTreeRoot" in pdf.Root


def auto_tag_pdf(
    source_path: Path,
    output_path: Optional[Path] = None,
    overwrite_tags: bool = False,
) -> Dict[str, Any]:
    """
    Analyze a PDF with OpenDataLoader and write structure tags with pikepdf.
    """
    target = output_path or source_path

    try:
        analyzer = DocumentLayoutAnalyzer()
        analyzer._ensure_runtime()
    except Exception as exc:
        return {
            "success": False,
            "error": str(exc),
            "output_path": str(target),
            "errors": [str(exc)],
            "warnings": [],
        }

    if not HAS_PIKEPDF:
        error = "pikepdf is required for PDF structure writing"
        return {
            "success": False,
            "error": error,
            "output_path": str(target),
            "errors": [error],
            "warnings": [],
        }

    try:
        already_tagged = _has_structure_tree(source_path)
    except Exception as exc:
        logger.warning("Could not inspect existing PDF tags: %s", exc)
        already_tagged = False

    if already_tagged and not overwrite_tags:
        if source_path.resolve() != target.resolve():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, target)
        return {
            "success": True,
            "skipped": True,
            "tags_created": 0,
            "tag_counts": {},
            "pages_processed": 0,
            "output_path": str(target),
            "errors": [],
            "warnings": ["Existing structure tree preserved"],
            "message": "Existing structure tree preserved",
        }

    try:
        layouts = analyzer.analyze_document(source_path)
        has_taggable_blocks = any(
            block.tag != "Artifact"
            for layout in layouts
            for block in layout.blocks
        )
        if not layouts or not has_taggable_blocks:
            error = "No content blocks detected in the document"
            return {
                "success": False,
                "error": error,
                "output_path": str(target),
                "errors": [error],
                "warnings": [],
            }

        builder = PDFStructureBuilder()
        result = builder.build_tagged_pdf(
            source_path,
            target,
            layouts,
            overwrite_existing_tags=overwrite_tags,
        )

        payload = {
            "success": result.success,
            "skipped": False,
            "tags_created": result.total_tags_created,
            "tag_counts": result.tag_counts,
            "pages_processed": result.total_pages,
            "output_path": str(target),
            "errors": result.errors,
            "warnings": result.warnings,
            "message": (
                f"Created {result.total_tags_created} structure tags across "
                f"{result.total_pages} pages"
                if result.success
                else "Auto-tagging failed"
            ),
        }
        if result.errors:
            payload["error"] = result.errors[0]
        return payload
    except Exception as exc:
        logger.error("OpenDataLoader auto-tagging failed: %s", exc, exc_info=True)
        return {
            "success": False,
            "error": str(exc),
            "output_path": str(target),
            "errors": [str(exc)],
            "warnings": [],
        }
