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
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

try:
    import pikepdf
    HAS_PIKEPDF = True
except ImportError:
    HAS_PIKEPDF = False


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
                if block.tag == "Artifact":
                    continue
                
                # Retrieve raw bounding box in PDF points if available, otherwise fallback to normalized
                raw_bbox = block.metadata.get("raw_bbox") if block.metadata else None
                bbox_coords = list(raw_bbox) if raw_bbox else []

                blocks_data.append({
                    "page": layout.page_number,
                    "tag": block.tag,
                    "bbox": bbox_coords
                })
                tag_counts[block.tag] = tag_counts.get(block.tag, 0) + 1

        # Step 3: Write layout JSON data to a temporary file
        fd, temp_json_path = tempfile.mkstemp(prefix="layout_blocks_", suffix=".json")
        try:
            with open(fd, 'w', encoding='utf-8') as f:
                json.dump(blocks_data, f, indent=2)

            # Step 4: Resolve C++ remediator executable path
            workspace_root = Path(__file__).resolve().parent.parent
            cpp_binary = workspace_root / "pdfua_remediator_cpp" / "build" / "Release" / "pdfua-remediator-cli.exe"

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
            try:
                subprocess.run(cmd, capture_output=True, text=True, check=True)
                logger.info("C++ QPDF engine finished successfully.")
                if use_temp_out:
                    shutil.move(actual_target, str(target))
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

        total_tags = len(blocks_data)
        return {
            "success": True,
            "skipped": False,
            "tags_created": total_tags,
            "tag_counts": tag_counts,
            "pages_processed": pages_processed,
            "output_path": str(target),
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
