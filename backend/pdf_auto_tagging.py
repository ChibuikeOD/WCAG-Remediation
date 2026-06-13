"""
Shared PDF auto-tagging service backed by OpenDataLoader and C++ QPDF engine.
"""
from __future__ import annotations

import logging
import os
import shutil
import tempfile
import json
import subprocess
import re
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

try:
    import pikepdf
    HAS_PIKEPDF = True
except ImportError:
    HAS_PIKEPDF = False


def _normalize_language_tag(language: Optional[str]) -> str:
    """Return a PAC-friendly BCP 47 language tag for PDF /Lang metadata."""
    if not language:
        return "en-US"

    lang = str(language).strip().replace("_", "-")
    if not lang:
        return "en-US"

    lower = lang.lower()
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
        "turkish": "tr",
    }
    if lower in name_to_code:
        return name_to_code[lower]

    if not re.fullmatch(r"[a-zA-Z]{2,3}(?:-[a-zA-Z0-9]{1,8})*", lang):
        return "en-US"

    parts = lower.split("-")
    for index, part in enumerate(parts[1:], start=1):
        if index == 1 and len(part) == 2 and part.isalpha():
            parts[index] = part.upper()
        elif index == 1 and len(part) == 4 and part.isalpha():
            parts[index] = part.title()

    return "-".join(parts)


def _finalize_language_metadata(pdf_path: Path) -> Optional[str]:
    """Normalize catalog /Lang and XMP dc:language on a completed PDF."""
    if not HAS_PIKEPDF:
        return None

    with pikepdf.open(str(pdf_path), allow_overwriting_input=True) as pdf:
        raw_lang = pdf.Root.get("/Lang")
        normalized = _normalize_language_tag(str(raw_lang) if raw_lang is not None else None)
        pdf.Root.Lang = pikepdf.String(normalized)
        with pdf.open_metadata(set_pikepdf_as_editor=True, update_docinfo=True) as meta:
            meta["dc:language"] = [normalized]
        pdf.save()
    return normalized


def _has_structure_tree(pdf_path: Path) -> bool:
    if not HAS_PIKEPDF:
        return False

    with pikepdf.open(str(pdf_path)) as pdf:
        return "/StructTreeRoot" in pdf.Root


def auto_tag_pdf(
    source_path: Path,
    output_path: Optional[Path] = None,
    overwrite_tags: bool = False,
    model_path: str = "",
    confidence_threshold: float = 0.0,
) -> Dict[str, Any]:
    """
    Analyze a PDF and write PDF/UA physical structure tags using OpenDataLoader + C++ QPDF engine.
    """
    target = output_path or source_path

    try:
        if not overwrite_tags and _has_structure_tree(source_path):
            if source_path.resolve() != target.resolve():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_path, target)
            return {
                "success": True,
                "skipped": True,
                "tags_created": 0,
                "pages_processed": 0,
                "output_path": str(target),
                "errors": [],
                "warnings": ["Existing structure tree preserved"],
                "message": "Existing structure tree preserved",
            }

        # Step 1: Run Layout Analysis using OpenDataLoader PDF
        from .opendataloader_layout import OpenDataLoaderLayoutAnalyzer

        logger.info("Extracting document layout using OpenDataLoader PDF...")
        analyzer = OpenDataLoaderLayoutAnalyzer()
        layouts = analyzer.analyze_document(source_path)

        # Step 2: Normalize and extract layout blocks coordinates
        blocks_data = []
        tag_counts = {}
        pages_processed = len(layouts)

        for layout in layouts:
            for block in layout.blocks:
                # Retrieve raw bounding box in PDF points if available, otherwise fallback to normalized
                raw_bbox = block.metadata.get("raw_bbox") if block.metadata else None
                bbox_coords = list(raw_bbox) if raw_bbox else []

                block_data = {
                    "page": layout.page_number,
                    "tag": block.tag,
                    "bbox": bbox_coords
                }
                for key in ("table_id", "table_row", "table_col", "table_header"):
                    if key in block.metadata:
                        block_data[key] = block.metadata[key]

                blocks_data.append(block_data)
                tag_counts[block.tag] = tag_counts.get(block.tag, 0) + 1

        # Step 3: Write layout JSON data to a temporary file
        fd, temp_json_path = tempfile.mkstemp(prefix="layout_blocks_", suffix=".json")
        try:
            with open(fd, 'w', encoding='utf-8') as f:
                json.dump(blocks_data, f)

            # Step 4: Resolve C++ remediator executable path cross-platform
            workspace_root = Path(__file__).resolve().parent.parent
            import sys
            if sys.platform.startswith("win"):
                cpp_binary = workspace_root / "pdfua_remediator_cpp" / "build" / "Release" / "pdfua-remediator-cli.exe"
            else:
                cpp_binary = workspace_root / "pdfua_remediator_cpp" / "build" / "pdfua-remediator-cli"
                if not cpp_binary.exists():
                    cpp_binary = workspace_root / "pdfua_remediator_cpp" / "build" / "Release" / "pdfua-remediator-cli"

            if not cpp_binary.exists():
                raise FileNotFoundError(f"Compiled C++ remediator CLI executable not found at '{cpp_binary}'. Please build it first.")

            # Step 5: Execute the C++ QPDF binary to inject MCIDs and tags
            logger.info("Running C++ QPDF engine to inject MCIDs and structure tree...")
            
            use_temp_out = (source_path.resolve() == target.resolve())
            actual_target = str(target)
            temp_out_path = None
            if use_temp_out:
                fd_out, temp_out_path = tempfile.mkstemp(prefix="tagged_pdf_", suffix=".pdf")
                os.close(fd_out)
                actual_target = temp_out_path

            cmd = [
                str(cpp_binary),
                str(source_path),
                str(temp_json_path),
                actual_target
            ]
            
            # Execute the C++ CLI tool
            from .config import settings

            try:
                res = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=settings.PDF_SUBPROCESS_TIMEOUT_SECONDS,
                )
                logger.info("C++ QPDF engine finished successfully.")
                if use_temp_out:
                    shutil.move(actual_target, str(target))
            except subprocess.TimeoutExpired as err:
                logger.error(
                    "C++ remediator CLI timed out after %ss",
                    settings.PDF_SUBPROCESS_TIMEOUT_SECONDS,
                )
                raise RuntimeError(
                    "C++ remediator CLI timed out after "
                    f"{settings.PDF_SUBPROCESS_TIMEOUT_SECONDS}s"
                ) from err
            except subprocess.CalledProcessError as err:
                logger.error("C++ remediator CLI failed with exit code %d", err.returncode)
                logger.error("STDOUT:\n%s", err.stdout)
                logger.error("STDERR:\n%s", err.stderr)
                raise RuntimeError(f"C++ remediator CLI failed: {err.stderr.strip()}") from err
            finally:
                if use_temp_out and temp_out_path:
                    try:
                        Path(temp_out_path).unlink(missing_ok=True)
                    except Exception:
                        pass

        finally:
            # Always clean up the temporary layout JSON file
            try:
                Path(temp_json_path).unlink(missing_ok=True)
            except Exception:
                pass

        normalized_language = _finalize_language_metadata(target)

        total_tags = len(blocks_data)
        return {
            "success": True,
            "skipped": False,
            "tags_created": total_tags,
            "tag_counts": tag_counts,
            "pages_processed": pages_processed,
            "output_path": str(target),
            "language": normalized_language,
            "errors": [],
            "warnings": [],
            "message": f"Successfully auto-tagged {pages_processed} pages",
        }

    except Exception as exc:
        logger.error("Auto-tagging failed: %s", exc, exc_info=True)
        return {
            "success": False,
            "error": str(exc),
            "output_path": str(target),
            "errors": [str(exc)],
            "warnings": [],
        }
