"""
Compare LayoutLMv3 vs OpenDataLoader layout/tagging outputs on the same PDF.
"""
from __future__ import annotations

import json
import logging
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .layout_model import DocumentLayoutAnalyzer, PageLayout, StructureBlock
from .opendataloader_layout import OpenDataLoaderLayoutAnalyzer
from .pdf_overlay_debug import generate_block_overlays_zip

logger = logging.getLogger(__name__)

IOU_MATCH_THRESHOLD = 0.25


@dataclass
class PipelineRunResult:
    provider: str
    success: bool
    layouts: List[PageLayout]
    error: Optional[str] = None
    runtime_description: str = ""


def _tag_counts(layouts: List[PageLayout]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for layout in layouts:
        for block in layout.blocks:
            counts[block.tag] = counts.get(block.tag, 0) + 1
    return counts


def _bbox_iou(a: Tuple[int, int, int, int], b: Tuple[int, int, int, int]) -> float:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    inter_x0 = max(ax0, bx0)
    inter_y0 = max(ay0, by0)
    inter_x1 = min(ax1, bx1)
    inter_y1 = min(ay1, by1)
    if inter_x1 <= inter_x0 or inter_y1 <= inter_y0:
        return 0.0
    inter_area = (inter_x1 - inter_x0) * (inter_y1 - inter_y0)
    area_a = max(1, (ax1 - ax0) * (ay1 - ay0))
    area_b = max(1, (bx1 - bx0) * (by1 - by0))
    return inter_area / float(area_a + area_b - inter_area)


def _block_preview(block: StructureBlock, max_len: int = 60) -> str:
    text = block.text.replace("\n", " ").strip()
    if len(text) > max_len:
        return text[: max_len - 3] + "..."
    return text


def _match_blocks_on_page(
    left: List[StructureBlock],
    right: List[StructureBlock],
    *,
    left_name: str,
    right_name: str,
) -> Dict[str, Any]:
    """Greedy IoU matching between two block lists on the same page."""
    unused_right = list(range(len(right)))
    matches: List[Dict[str, Any]] = []
    disagreements: List[Dict[str, Any]] = []
    left_only: List[Dict[str, Any]] = []

    for li, lblock in enumerate(left):
        if lblock.bbox is None:
            left_only.append(
                {
                    "provider": left_name,
                    "tag": lblock.tag,
                    "text": _block_preview(lblock),
                }
            )
            continue

        best_j = None
        best_iou = 0.0
        for j in unused_right:
            rblock = right[j]
            if rblock.bbox is None:
                continue
            iou = _bbox_iou(lblock.bbox, rblock.bbox)
            if iou > best_iou:
                best_iou = iou
                best_j = j

        if best_j is None or best_iou < IOU_MATCH_THRESHOLD:
            left_only.append(
                {
                    "provider": left_name,
                    "tag": lblock.tag,
                    "text": _block_preview(lblock),
                    "bbox": lblock.bbox,
                }
            )
            continue

        rblock = right[best_j]
        unused_right.remove(best_j)
        match_info = {
            "iou": round(best_iou, 3),
            f"{left_name}_tag": lblock.tag,
            f"{right_name}_tag": rblock.tag,
            "text": _block_preview(lblock) or _block_preview(rblock),
            f"{left_name}_source": lblock.metadata.get("source_label")
            or lblock.metadata.get("source_type"),
            f"{right_name}_source": rblock.metadata.get("source_type"),
        }
        matches.append(match_info)
        if lblock.tag != rblock.tag:
            disagreements.append(match_info)

    right_only: List[Dict[str, Any]] = []
    for j in unused_right:
        rblock = right[j]
        right_only.append(
            {
                "provider": right_name,
                "tag": rblock.tag,
                "text": _block_preview(rblock),
                "bbox": rblock.bbox,
            }
        )

    tag_agreements = len(matches) - len(disagreements)
    return {
        "matched_pairs": len(matches),
        "tag_agreements": tag_agreements,
        "tag_disagreements": len(disagreements),
        "agreement_rate": round(tag_agreements / len(matches), 3) if matches else None,
        "disagreements": disagreements[:50],
        f"{left_name}_only": left_only[:30],
        f"{right_name}_only": right_only[:30],
    }


def compare_layouts(
    layoutlm_layouts: List[PageLayout],
    odl_layouts: List[PageLayout],
) -> Dict[str, Any]:
    """Build a structured comparison report."""
    ll_counts = _tag_counts(layoutlm_layouts)
    odl_counts = _tag_counts(odl_layouts)
    all_tags = sorted(set(ll_counts) | set(odl_counts))

    tag_count_diff = {
        tag: {
            "layoutlm": ll_counts.get(tag, 0),
            "opendataloader": odl_counts.get(tag, 0),
            "delta": ll_counts.get(tag, 0) - odl_counts.get(tag, 0),
        }
        for tag in all_tags
    }

    page_count = max(len(layoutlm_layouts), len(odl_layouts))
    pages: List[Dict[str, Any]] = []
    total_matched = 0
    total_agreements = 0
    total_disagreements = 0

    for page_index in range(page_count):
        ll_blocks = (
            layoutlm_layouts[page_index].blocks if page_index < len(layoutlm_layouts) else []
        )
        odl_blocks = odl_layouts[page_index].blocks if page_index < len(odl_layouts) else []
        page_cmp = _match_blocks_on_page(
            ll_blocks,
            odl_blocks,
            left_name="layoutlm",
            right_name="opendataloader",
        )
        total_matched += page_cmp["matched_pairs"]
        total_agreements += page_cmp["tag_agreements"]
        total_disagreements += page_cmp["tag_disagreements"]
        pages.append(
            {
                "page_number": page_index + 1,
                "layoutlm_blocks": len(ll_blocks),
                "opendataloader_blocks": len(odl_blocks),
                **page_cmp,
            }
        )

    return {
        "summary": {
            "pages": page_count,
            "layoutlm": {
                "blocks": sum(len(layout.blocks) for layout in layoutlm_layouts),
                "tag_counts": ll_counts,
            },
            "opendataloader": {
                "blocks": sum(len(layout.blocks) for layout in odl_layouts),
                "tag_counts": odl_counts,
            },
            "matched_block_pairs": total_matched,
            "tag_agreements": total_agreements,
            "tag_disagreements": total_disagreements,
            "overall_agreement_rate": round(total_agreements / total_matched, 3)
            if total_matched
            else None,
        },
        "tag_count_diff": tag_count_diff,
        "pages": pages,
    }


def run_layoutlm_pipeline(file_path: Path, confidence_threshold: float = 0.0) -> PipelineRunResult:
    try:
        analyzer = DocumentLayoutAnalyzer(confidence_threshold=confidence_threshold)
        analyzer._ensure_model()
        layouts = analyzer.analyze_document(file_path)
        return PipelineRunResult(
            provider="layoutlm",
            success=True,
            layouts=layouts,
            runtime_description="layoutLM_trained",
        )
    except Exception as exc:
        logger.error("LayoutLM pipeline failed: %s", exc, exc_info=True)
        return PipelineRunResult(
            provider="layoutlm",
            success=False,
            layouts=[],
            error=str(exc),
        )


def run_opendataloader_pipeline(file_path: Path) -> PipelineRunResult:
    try:
        analyzer = OpenDataLoaderLayoutAnalyzer()
        runtime = analyzer._ensure_runtime()
        layouts = analyzer.analyze_document(file_path)
        return PipelineRunResult(
            provider="opendataloader",
            success=True,
            layouts=layouts,
            runtime_description=runtime.description,
        )
    except Exception as exc:
        logger.error("OpenDataLoader pipeline failed: %s", exc, exc_info=True)
        return PipelineRunResult(
            provider="opendataloader",
            success=False,
            layouts=[],
            error=str(exc),
        )


def run_tagging_comparison(
    file_path: Path,
    *,
    confidence_threshold: float = 0.0,
) -> Dict[str, Any]:
    """Run both pipelines and return a comparison report."""
    ll_result = run_layoutlm_pipeline(file_path, confidence_threshold=confidence_threshold)
    odl_result = run_opendataloader_pipeline(file_path)

    report: Dict[str, Any] = {
        "document": file_path.name,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "pipelines": {
            "layoutlm": {
                "success": ll_result.success,
                "error": ll_result.error,
                "runtime": ll_result.runtime_description,
            },
            "opendataloader": {
                "success": odl_result.success,
                "error": odl_result.error,
                "runtime": odl_result.runtime_description,
            },
        },
    }

    if ll_result.success and odl_result.success:
        report["comparison"] = compare_layouts(ll_result.layouts, odl_result.layouts)
    else:
        report["comparison"] = None
        report["comparison_error"] = (
            "Both pipelines must succeed to compute a comparison. "
            f"layoutlm_ok={ll_result.success}, opendataloader_ok={odl_result.success}"
        )

    report["_layouts"] = {
        "layoutlm": ll_result.layouts,
        "opendataloader": odl_result.layouts,
    }
    return report


def save_comparison_report(report: Dict[str, Any], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(report["document"]).stem
    out_path = output_dir / f"tagging_compare_{stem}.json"
    serializable = {k: v for k, v in report.items() if not k.startswith("_")}
    out_path.write_text(json.dumps(serializable, indent=2), encoding="utf-8")
    return out_path


def build_comparison_bundle(
    file_path: Path,
    report: Dict[str, Any],
    output_dir: Path,
) -> Path:
    """
    ZIP containing comparison.json plus overlay PNGs for each pipeline.
    """
    layouts = report.get("_layouts") or {}
    output_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = output_dir / f"tagging_compare_{file_path.stem}.zip"

    comparison_json = {k: v for k, v in report.items() if not k.startswith("_")}

    with zipfile.ZipFile(bundle_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("comparison.json", json.dumps(comparison_json, indent=2))

        for provider, provider_layouts in layouts.items():
            if not provider_layouts:
                continue
            provider_zip = generate_block_overlays_zip(
                file_path,
                provider_layouts,
                output_dir,
                zip_name=f"_tmp_{provider}_{file_path.stem}.zip",
            )
            prefix = f"{provider}/"
            with zipfile.ZipFile(provider_zip, "r") as inner:
                for name in inner.namelist():
                    zf.writestr(prefix + name, inner.read(name))
            provider_zip.unlink(missing_ok=True)

    return bundle_path


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Compare LayoutLM vs OpenDataLoader tagging on a PDF."
    )
    parser.add_argument("pdf", type=Path, help="Path to input PDF")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output"),
        help="Directory for JSON report and optional ZIP bundle",
    )
    parser.add_argument(
        "--bundle",
        action="store_true",
        help="Also write a ZIP with comparison.json and overlay images for both pipelines",
    )
    parser.add_argument(
        "--confidence-threshold",
        type=float,
        default=0.0,
        help="LayoutLM minimum token confidence",
    )
    args = parser.parse_args()

    report = run_tagging_comparison(
        args.pdf,
        confidence_threshold=args.confidence_threshold,
    )
    json_path = save_comparison_report(report, args.output_dir)
    print(f"Wrote {json_path}")

    if args.bundle:
        zip_path = build_comparison_bundle(args.pdf, report, args.output_dir)
        print(f"Wrote {zip_path}")

    summary = (report.get("comparison") or {}).get("summary")
    if summary:
        print(
            f"Agreement: {summary.get('tag_agreements')}/{summary.get('matched_block_pairs')} "
            f"matched pairs ({summary.get('overall_agreement_rate')})"
        )


if __name__ == "__main__":
    main()
