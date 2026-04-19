"""
Provider-neutral PDF layout analysis backed by OpenDataLoader extraction.
"""
from __future__ import annotations

import importlib
import importlib.metadata
import json
import logging
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

try:
    import fitz  # PyMuPDF
    HAS_PYMUPDF = True
except ImportError:
    HAS_PYMUPDF = False


INSTALLED_ODL_VERSION = "2.2.1"
LOCAL_JAR_GLOB = "java/opendataloader-pdf-cli/target/opendataloader-pdf-cli-*.jar"


@dataclass
class WordPrediction:
    """
    Legacy container preserved for compatibility with existing imports.

    OpenDataLoader operates on block-level structure, so the active pipeline
    leaves these predictions empty.
    """

    text: str
    bbox: Tuple[int, int, int, int]
    label: str
    confidence: float = 1.0
    font_size: Optional[float] = None
    is_bold: Optional[bool] = None


@dataclass
class StructureBlock:
    """A logical document block ready to map into PDF tags."""

    tag: str
    bbox: Optional[Tuple[int, int, int, int]] = None
    page_number: int = 0
    heading_level: Optional[int] = None
    content: str = ""
    words: List[WordPrediction] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def text(self) -> str:
        if self.content:
            return self.content
        return " ".join(word.text for word in self.words).strip()

    def compute_bbox(self):
        if self.bbox is not None:
            return
        if not self.words:
            return
        x0 = min(word.bbox[0] for word in self.words)
        y0 = min(word.bbox[1] for word in self.words)
        x1 = max(word.bbox[2] for word in self.words)
        y1 = max(word.bbox[3] for word in self.words)
        self.bbox = (x0, y0, x1, y1)


@dataclass
class PageLayout:
    """Layout analysis result for a single page."""

    page_number: int
    width: float
    height: float
    blocks: List[StructureBlock] = field(default_factory=list)
    word_predictions: List[WordPrediction] = field(default_factory=list)


@dataclass
class RuntimeResolution:
    """Resolved OpenDataLoader runtime."""

    kind: str
    description: str
    jar_path: Optional[Path] = None


class DocumentLayoutAnalyzer:
    """
    Analyze PDFs into provider-neutral structure blocks using OpenDataLoader.
    """

    _instance: Optional["DocumentLayoutAnalyzer"] = None

    def __init__(self, model_path: str = "", confidence_threshold: float = 0.0):
        self.model_path = model_path
        self.confidence_threshold = confidence_threshold
        self._runtime: Optional[RuntimeResolution] = None

    @classmethod
    def get_instance(cls, model_path: str = "", confidence_threshold: float = 0.0) -> "DocumentLayoutAnalyzer":
        if cls._instance is None:
            cls._instance = cls(model_path=model_path, confidence_threshold=confidence_threshold)
        return cls._instance

    @staticmethod
    def is_available() -> bool:
        analyzer = DocumentLayoutAnalyzer()
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
                "OpenDataLoader PDF analysis requires Java on PATH. "
                "Install Java and ensure the `java` command is available."
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
                    f"Install version {INSTALLED_ODL_VERSION}, or build the local checkout at "
                    f"'{root}'."
                )
            importlib.import_module("opendataloader_pdf")
            logger.info("Using installed opendataloader-pdf %s", version)
            return RuntimeResolution(
                kind="installed-package",
                description=f"installed opendataloader-pdf {version}",
            )

        raise RuntimeError(
            "OpenDataLoader runtime not available. Either build the local checkout at "
            f"'{root}' (run `mvn package` under `java/`, then build/install the Python wheel) "
            f"or install `opendataloader-pdf=={INSTALLED_ODL_VERSION}`."
        )

    def _run_local_jar(self, input_path: Path, output_dir: Path, runtime: RuntimeResolution):
        if runtime.jar_path is None:
            raise RuntimeError("Local OpenDataLoader runtime is missing a CLI JAR")
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
            )
        except subprocess.CalledProcessError as exc:
            message = exc.stderr or exc.stdout or str(exc)
            raise RuntimeError(f"OpenDataLoader CLI failed: {message.strip()}") from exc

    def _run_installed_package(self, input_path: Path, output_dir: Path):
        try:
            package = importlib.import_module("opendataloader_pdf")
        except ImportError as exc:
            raise RuntimeError(
                f"Installed OpenDataLoader package could not be imported: {exc}"
            ) from exc

        try:
            package.convert(
                input_path=str(input_path),
                output_dir=str(output_dir),
                format="json",
                include_header_footer=True,
                use_struct_tree=False,
            )
        except Exception as exc:
            raise RuntimeError(f"OpenDataLoader package conversion failed: {exc}") from exc

    def _convert_with_opendataloader(self, input_path: Path) -> Path:
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
        bbox: Iterable[float],
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
                child_text = DocumentLayoutAnalyzer._extract_text(child)
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
        normalized_bbox = DocumentLayoutAnalyzer._normalize_bbox(bbox, page_width, page_height)

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
            content=DocumentLayoutAnalyzer._extract_text(element),
            metadata={
                "source_type": raw_type,
                "source_id": element.get("id"),
                "page_width": page_width,
                "page_height": page_height,
            },
        )

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

        return layouts

    def analyze_page(self, page: "fitz.Page", page_number: int = 0) -> PageLayout:
        raise NotImplementedError(
            "Single-page analysis is not supported in the OpenDataLoader-backed analyzer. "
            "Use analyze_document(file_path) instead."
        )

    def analyze_document(self, file_path: Path) -> List[PageLayout]:
        json_copy = self._convert_with_opendataloader(file_path)
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

    def get_tag_summary(self, layouts: List[PageLayout]) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for layout in layouts:
            for block in layout.blocks:
                counts[block.tag] = counts.get(block.tag, 0) + 1
        return counts
