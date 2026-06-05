"""
PDF layout analysis using OpenDataLoader extraction (block-level JSON).
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
