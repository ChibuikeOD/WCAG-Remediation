"""
PDF layout analysis using OpenDataLoader extraction (block-level JSON).
"""
from __future__ import annotations

import importlib
import importlib.metadata
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .layout_model import PageLayout, StructureBlock

logger = logging.getLogger(__name__)

try:
    import fitz
    HAS_PYMUPDF = True
except ImportError:
    HAS_PYMUPDF = False

INSTALLED_ODL_VERSION = "2.2.1"
LOCAL_JAR_GLOB = "java/opendataloader-pdf-cli/target/opendataloader-pdf-cli-*.jar"


@dataclass
class RuntimeResolution:
    kind: str
    description: str
    jar_path: Optional[Path] = None


class OpenDataLoaderLayoutAnalyzer:
    """Analyze PDFs via OpenDataLoader JSON export."""

    LIKERT_HEADERS = [
        "Definitely False",
        "Possibly False",
        "Not Sure",
        "Possibly True",
        "Definitely True",
    ]
    _PERCENT_RE = re.compile(r"-|\d+(?:\.\d+)?%")

    def __init__(self):
        self._runtime: Optional[RuntimeResolution] = None

    @staticmethod
    def is_available() -> bool:
        analyzer = OpenDataLoaderLayoutAnalyzer()
        try:
            analyzer._ensure_runtime()
            return True
        except Exception:
            return False

    def get_setup_error(self) -> str:
        try:
            self._ensure_runtime()
            return ""
        except Exception as exc:
            return str(exc)

    def _ensure_runtime(self) -> RuntimeResolution:
        if not HAS_PYMUPDF:
            raise RuntimeError("PyMuPDF is required for PDF analysis")
        if shutil.which("java") is None:
            raise RuntimeError(
                "OpenDataLoader requires Java on PATH. Install Java and ensure `java` is available."
            )
        if self._runtime is None:
            self._runtime = self._resolve_runtime()
        return self._runtime

    def _resolve_runtime(self) -> RuntimeResolution:
        from .config import settings

        root = settings.OPENDATALOADER_ROOT
        jar_candidates = sorted(root.glob(LOCAL_JAR_GLOB))
        if jar_candidates:
            jar_path = jar_candidates[-1]
            logger.info("Using local OpenDataLoader CLI JAR at %s", jar_path)
            return RuntimeResolution(
                kind="local-jar",
                description=f"local OpenDataLoader checkout ({jar_path})",
                jar_path=jar_path,
            )

        try:
            version = importlib.metadata.version("opendataloader-pdf")
        except importlib.metadata.PackageNotFoundError:
            version = None

        if version:
            if version != INSTALLED_ODL_VERSION:
                raise RuntimeError(
                    f"Installed opendataloader-pdf version {version} is unsupported. "
                    f"Install version {INSTALLED_ODL_VERSION}, or build the local checkout at '{root}'."
                )
            importlib.import_module("opendataloader_pdf")
            logger.info("Using installed opendataloader-pdf %s", version)
            return RuntimeResolution(
                kind="installed-package",
                description=f"installed opendataloader-pdf {version}",
            )

        raise RuntimeError(
            "OpenDataLoader runtime not available. Either build the local checkout at "
            f"'{root}' (run `mvn package` under `java/`) or install "
            f"`opendataloader-pdf=={INSTALLED_ODL_VERSION}`."
        )

    def _run_local_jar(self, input_path: Path, output_dir: Path, runtime: RuntimeResolution):
        if runtime.jar_path is None:
            raise RuntimeError("Local OpenDataLoader runtime is missing a CLI JAR")
        from .config import settings

        command = [
            "java",
            "-jar",
            str(runtime.jar_path),
            str(input_path),
            "--output-dir",
            str(output_dir),
            "--format",
            "json",
            "--include-header-footer",
        ]
        try:
            subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                timeout=settings.PDF_SUBPROCESS_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                "OpenDataLoader CLI timed out after "
                f"{settings.PDF_SUBPROCESS_TIMEOUT_SECONDS}s (likely out of memory "
                "or too large a document for the current Java heap)."
            ) from exc
        except subprocess.CalledProcessError as exc:
            message = exc.stderr or exc.stdout or str(exc)
            raise RuntimeError(f"OpenDataLoader CLI failed: {message.strip()}") from exc

    def _run_installed_package(self, input_path: Path, output_dir: Path):
        from .config import settings

        timeout = settings.PDF_SUBPROCESS_TIMEOUT_SECONDS

        # Prefer invoking the bundled CLI JAR directly so we can enforce a hard
        # wall-clock timeout. The package's own runner.run_jar() has no timeout,
        # so a wedged/OOM-thrashing JVM would otherwise hang the request forever.
        jar_path = self._locate_bundled_jar()
        if jar_path is not None:
            command = [
                "java",
                "-jar",
                str(jar_path),
                str(input_path),
                "--output-dir",
                str(output_dir),
                "--format",
                "json",
                "--include-header-footer",
            ]
            try:
                subprocess.run(
                    command,
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
                return
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError(
                    f"OpenDataLoader CLI timed out after {timeout}s (likely out of "
                    "memory or too large a document for the current Java heap)."
                ) from exc
            except subprocess.CalledProcessError as exc:
                message = exc.stderr or exc.stdout or str(exc)
                raise RuntimeError(f"OpenDataLoader CLI failed: {message.strip()}") from exc

        # Fallback: the bundled JAR could not be located, so defer to the
        # package's own convert(). No timeout is possible on this path.
        package = importlib.import_module("opendataloader_pdf")
        package.convert(
            input_path=str(input_path),
            output_dir=str(output_dir),
            format="json",
            include_header_footer=True,
            use_struct_tree=False,
        )

    @staticmethod
    def _locate_bundled_jar() -> Optional[Path]:
        """Resolve the path to the CLI JAR shipped inside opendataloader_pdf."""
        try:
            import importlib.resources as resources

            jar_ref = resources.files("opendataloader_pdf").joinpath(
                "jar", "opendataloader-pdf-cli.jar"
            )
            with resources.as_file(jar_ref) as jar_path:
                jar = Path(jar_path)
                return jar if jar.exists() else None
        except Exception as exc:
            logger.debug("Could not locate bundled OpenDataLoader JAR: %s", exc)
            return None

    def _convert_to_json(self, input_path: Path) -> Path:
        runtime = self._ensure_runtime()
        with tempfile.TemporaryDirectory(prefix="odl_pdf_") as temp_dir:
            out_dir = Path(temp_dir)
            if runtime.kind == "local-jar":
                self._run_local_jar(input_path, out_dir, runtime)
            else:
                self._run_installed_package(input_path, out_dir)

            json_path = out_dir / f"{input_path.stem}.json"
            if not json_path.exists():
                raise RuntimeError(
                    f"OpenDataLoader did not create the expected JSON output at '{json_path}'."
                )

            fd, stable_path = tempfile.mkstemp(prefix="odl_layout_", suffix=".json")
            os.close(fd)
            stable_copy = Path(stable_path)
            stable_copy.write_text(json_path.read_text(encoding="utf-8"), encoding="utf-8")
            return stable_copy

    @staticmethod
    def _load_page_sizes(file_path: Path) -> List[Tuple[float, float]]:
        doc = fitz.open(str(file_path))
        try:
            return [(page.rect.width, page.rect.height) for page in doc]
        finally:
            doc.close()

    @staticmethod
    def _normalize_bbox(
        bbox: List[float],
        page_width: float,
        page_height: float,
    ) -> Tuple[int, int, int, int]:
        left, bottom, right, top = bbox
        if page_width <= 0 or page_height <= 0:
            return (0, 0, 0, 0)

        x0 = int(max(0.0, min(1000.0, (left / page_width) * 1000.0)))
        x1 = int(max(0.0, min(1000.0, (right / page_width) * 1000.0)))
        y0 = int(max(0.0, min(1000.0, ((page_height - top) / page_height) * 1000.0)))
        y1 = int(max(0.0, min(1000.0, ((page_height - bottom) / page_height) * 1000.0)))
        return (x0, y0, x1, y1)

    @staticmethod
    def _extract_text(element: Dict[str, Any]) -> str:
        text = str(element.get("content", "") or "").strip()
        if text:
            return text

        nested_parts: List[str] = []
        for key in ("kids", "list items", "rows", "cells"):
            for child in element.get(key, []) or []:
                child_text = OpenDataLoaderLayoutAnalyzer._extract_text(child)
                if child_text:
                    nested_parts.append(child_text)
        return " ".join(part for part in nested_parts if part).strip()

    @staticmethod
    def _map_element_to_block(
        element: Dict[str, Any],
        page_sizes: List[Tuple[float, float]],
    ) -> Optional[StructureBlock]:
        raw_type = str(element.get("type", "") or "").strip().lower()
        page_num = element.get("page number")
        bbox = element.get("bounding box")

        if not raw_type or not isinstance(page_num, int) or page_num <= 0 or not bbox:
            return None
        page_index = page_num - 1
        if page_index >= len(page_sizes):
            return None

        page_width, page_height = page_sizes[page_index]
        normalized_bbox = OpenDataLoaderLayoutAnalyzer._normalize_bbox(
            bbox, page_width, page_height
        )

        tag = None
        heading_level = None
        if raw_type == "heading":
            level = int(element.get("heading level", 1) or 1)
            heading_level = max(1, min(6, level))
            tag = f"H{heading_level}"
        elif raw_type in {"paragraph", "text block"}:
            tag = "P"
        elif raw_type == "list":
            tag = "L"
        elif raw_type == "list item":
            tag = "LI"
        elif raw_type == "table":
            tag = "Table"
        elif raw_type == "image":
            tag = "Figure"
        elif raw_type == "caption":
            tag = "Caption"
        elif raw_type in {"header", "footer"}:
            tag = "Artifact"
        else:
            return None

        return StructureBlock(
            tag=tag,
            bbox=normalized_bbox,
            page_number=page_index,
            heading_level=heading_level,
            content=OpenDataLoaderLayoutAnalyzer._extract_text(element),
            metadata={
                "source_type": raw_type,
                "source_id": element.get("id"),
                "provider": "opendataloader",
                "raw_bbox": bbox,
            },
        )

    @classmethod
    def _is_likert_header_run(cls, blocks: List[StructureBlock], start: int) -> bool:
        if start + 3 >= len(blocks):
            return False
        if re.match(r"^\s*Table\s+\d+\b", blocks[start].text, re.IGNORECASE):
            return False
        combined = " ".join(block.text for block in blocks[start:start + 5])
        return sum(header in combined for header in cls.LIKERT_HEADERS) >= 4

    @classmethod
    def _table_id_for_header(
        cls,
        blocks: List[StructureBlock],
        header_start: int,
        page_number: int,
        fallback_index: int,
    ) -> str:
        for idx in range(header_start - 1, max(-1, header_start - 4), -1):
            match = re.search(r"\bTable\s+(\d+)\b", blocks[idx].text, re.IGNORECASE)
            if match:
                return f"p{page_number + 1}_table_{match.group(1)}"
        return f"p{page_number + 1}_table_{fallback_index}"

    @classmethod
    def _percent_values(cls, text: str) -> List[str]:
        return cls._PERCENT_RE.findall(text)

    @staticmethod
    def _raw_bbox(block: StructureBlock) -> Optional[List[float]]:
        raw_bbox = block.metadata.get("raw_bbox") if block.metadata else None
        if isinstance(raw_bbox, list) and len(raw_bbox) == 4:
            return [float(value) for value in raw_bbox]
        return None

    @classmethod
    def _make_table_cell(
        cls,
        *,
        text: str,
        raw_bbox: List[float],
        layout: PageLayout,
        table_id: str,
        row: int,
        col: int,
        header: bool,
    ) -> StructureBlock:
        normalized = cls._normalize_bbox(raw_bbox, layout.width, layout.height)
        return StructureBlock(
            tag="TH" if header else "TD",
            bbox=normalized,
            page_number=layout.page_number,
            content=text,
            metadata={
                "source_type": "inferred table cell",
                "provider": "opendataloader",
                "raw_bbox": raw_bbox,
                "table_id": table_id,
                "table_row": row,
                "table_col": col,
                "table_header": header,
            },
        )

    @classmethod
    def _split_value_bboxes(cls, value_bbox: List[float], count: int = 5) -> List[List[float]]:
        left, bottom, right, top = value_bbox
        left -= 8.0
        right += 4.0
        width = (right - left) / count if count else 0
        return [
            [left + width * idx, bottom, left + width * (idx + 1), top]
            for idx in range(count)
        ]

    @classmethod
    def _infer_table_cells_at(
        cls,
        layout: PageLayout,
        header_start: int,
        table_index: int,
    ) -> Tuple[List[StructureBlock], int]:
        blocks = layout.blocks
        header_blocks = blocks[header_start:header_start + 4]
        header_bboxes = [bbox for block in header_blocks if (bbox := cls._raw_bbox(block))]
        if not header_bboxes:
            return [], header_start

        table_id = cls._table_id_for_header(
            blocks,
            header_start,
            layout.page_number,
            table_index,
        )

        rows: List[Tuple[str, List[str], List[float], List[float]]] = []
        consumed_until = header_start + 4
        idx = consumed_until
        while idx < len(blocks):
            text = blocks[idx].text
            if re.match(r"^\s*Table\s+\d+\b", text, re.IGNORECASE):
                break
            if cls._is_likert_header_run(blocks, idx):
                break

            values = cls._percent_values(text)
            current_bbox = cls._raw_bbox(blocks[idx])
            if current_bbox and len(values) >= 3:
                label = cls._PERCENT_RE.sub("", text).strip()
                if label:
                    rows.append((label, values[:5], current_bbox, current_bbox))
                    idx += 1
                    consumed_until = idx
                    continue

            if idx + 1 < len(blocks):
                next_values = cls._percent_values(blocks[idx + 1].text)
                label_bbox = cls._raw_bbox(blocks[idx])
                value_bbox = cls._raw_bbox(blocks[idx + 1])
                if (
                    label_bbox
                    and value_bbox
                    and len(next_values) >= 3
                    and not cls._percent_values(blocks[idx].text)
                ):
                    rows.append((text, next_values[:5], label_bbox, value_bbox))
                    idx += 2
                    consumed_until = idx
                    continue

            idx += 1

        if not rows:
            return [], header_start

        cells: List[StructureBlock] = []
        min_label_left = min(row[2][0] for row in rows)
        max_label_top = max(bbox[3] for bbox in header_bboxes)
        min_header_bottom = min(bbox[1] for bbox in header_bboxes)
        first_value_bbox = rows[0][3]
        value_bboxes = cls._split_value_bboxes(first_value_bbox)
        header_value_bboxes = [
            [bbox[0], min_header_bottom, bbox[2], max_label_top]
            for bbox in value_bboxes
        ]
        statement_header_bbox = [
            min_label_left,
            min_header_bottom,
            first_value_bbox[0] - 12.0,
            max_label_top,
        ]

        header_labels = ["Statement", *cls.LIKERT_HEADERS]
        header_cell_bboxes = [statement_header_bbox, *header_value_bboxes]
        for col, (label, raw_bbox) in enumerate(zip(header_labels, header_cell_bboxes)):
            cells.append(
                cls._make_table_cell(
                    text=label,
                    raw_bbox=raw_bbox,
                    layout=layout,
                    table_id=table_id,
                    row=0,
                    col=col,
                    header=True,
                )
            )

        for row_number, (label, values, label_bbox, value_bbox) in enumerate(rows, start=1):
            row_value_bboxes = cls._split_value_bboxes(value_bbox, len(values))
            label_cell_bbox = [
                label_bbox[0],
                label_bbox[1],
                min(value_bbox[0] - 12.0, label_bbox[2]),
                label_bbox[3],
            ]
            cells.append(
                cls._make_table_cell(
                    text=label,
                    raw_bbox=label_cell_bbox,
                    layout=layout,
                    table_id=table_id,
                    row=row_number,
                    col=0,
                    header=True,
                )
            )
            for col, (value, raw_bbox) in enumerate(zip(values, row_value_bboxes), start=1):
                cells.append(
                    cls._make_table_cell(
                        text=value,
                        raw_bbox=raw_bbox,
                        layout=layout,
                        table_id=table_id,
                        row=row_number,
                        col=col,
                        header=False,
                    )
                )

        return cells, consumed_until

    @classmethod
    def _infer_likert_tables(cls, layouts: List[PageLayout]) -> None:
        for layout in layouts:
            enhanced_blocks: List[StructureBlock] = []
            idx = 0
            table_index = 1
            while idx < len(layout.blocks):
                if cls._is_likert_header_run(layout.blocks, idx):
                    cells, next_idx = cls._infer_table_cells_at(layout, idx, table_index)
                    if cells:
                        enhanced_blocks.extend(cells)
                        idx = next_idx
                        table_index += 1
                        continue
                enhanced_blocks.append(layout.blocks[idx])
                idx += 1
            layout.blocks = enhanced_blocks

    @classmethod
    def parse_opendataloader_json(
        cls,
        json_data: Dict[str, Any],
        page_sizes: List[Tuple[float, float]],
    ) -> List[PageLayout]:
        page_count = int(json_data.get("number of pages", len(page_sizes)) or len(page_sizes))
        layouts: List[PageLayout] = []
        for page_index in range(page_count):
            width, height = page_sizes[page_index] if page_index < len(page_sizes) else (0.0, 0.0)
            layouts.append(PageLayout(page_number=page_index, width=width, height=height))

        for element in json_data.get("kids", []) or []:
            block = cls._map_element_to_block(element, page_sizes)
            if block is None:
                continue
            layouts[block.page_number].blocks.append(block)

        cls._infer_likert_tables(layouts)

        return layouts

    def analyze_document(self, file_path: Path) -> List[PageLayout]:
        json_copy = self._convert_to_json(file_path)
        try:
            data = json.loads(json_copy.read_text(encoding="utf-8"))
        finally:
            json_copy.unlink(missing_ok=True)

        page_sizes = self._load_page_sizes(file_path)
        layouts = self.parse_opendataloader_json(data, page_sizes)
        total_blocks = sum(len(layout.blocks) for layout in layouts)
        logger.info(
            "OpenDataLoader layout analysis complete: %s pages, %s structure blocks",
            len(layouts),
            total_blocks,
        )
        return layouts
