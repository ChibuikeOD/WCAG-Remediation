"""
PDF layout analysis backed by a fine-tuned LayoutLMv3 token-classification model.
"""
from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

try:
    import fitz  # PyMuPDF
    HAS_PYMUPDF = True
except ImportError:
    HAS_PYMUPDF = False

try:
    from .config import settings
    if settings.DISABLE_LAYOUTLM:
        HAS_LAYOUTLM = False
    else:
        import torch
        from transformers import LayoutLMv3ForTokenClassification, LayoutLMv3Processor
        HAS_LAYOUTLM = True
except ImportError:
    HAS_LAYOUTLM = False

# Map DocLayNet-style labels to PDF structure tag names (before heading levels).
LABEL_TO_TAG: Dict[str, str] = {
    "Caption": "Caption",
    "Footnote": "Note",
    "Formula": "Formula",
    "List-item": "LI",
    "Page-footer": "Artifact",
    "Page-header": "Artifact",
    "Picture": "Figure",
    "Section-header": "H2",
    "Table": "Table",
    "Text": "P",
    "Title": "H1",
}

_HF_FILE_ALIASES: Dict[str, List[str]] = {
    "config.json": ["config.json", "config (3).json"],
    "tokenizer.json": ["tokenizer.json", "tokenizer (1).json"],
    "tokenizer_config.json": ["tokenizer_config.json", "tokenizer_config (1).json"],
    "processor_config.json": ["processor_config.json", "processor_config (1).json"],
    "model.safetensors": ["model.safetensors"],
}


@dataclass
class WordPrediction:
    """Per-word layout label from LayoutLMv3."""

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


def resolve_layoutlm_model_dir(model_path: str = "") -> Path:
    from .config import settings

    if model_path:
        return Path(model_path)
    return settings.LAYOUTLM_MODEL_DIR


def ensure_hf_model_layout(model_dir: Path) -> Path:
    """
    Return a directory whose files use HuggingFace-standard names.

    Copies aliased filenames (e.g. ``config (3).json``) into a cache folder
    when needed.
    """
    if (model_dir / "config.json").is_file() and (model_dir / "tokenizer.json").is_file():
        return model_dir

    from .config import settings

    cache = settings.BASE_DIR / ".cache" / "layoutlm_trained_hf"
    if cache.is_dir() and (cache / "config.json").is_file():
        return cache

    cache.mkdir(parents=True, exist_ok=True)
    for target_name, candidates in _HF_FILE_ALIASES.items():
        copied = False
        for candidate in candidates:
            src = model_dir / candidate
            if src.is_file():
                shutil.copy2(src, cache / target_name)
                copied = True
                break
        if not copied and target_name != "model.safetensors":
            raise FileNotFoundError(
                f"Missing LayoutLM model file '{target_name}' in '{model_dir}'. "
                f"Expected one of: {candidates}"
            )

    if not (cache / "model.safetensors").is_file():
        raise FileNotFoundError(f"Missing model weights in '{model_dir}'")

    return cache


class DocumentLayoutAnalyzer:
    """
    Analyze PDF pages with LayoutLMv3 and group token labels into structure blocks.
    """

    _instance: Optional["DocumentLayoutAnalyzer"] = None

    def __init__(self, model_path: str = "", confidence_threshold: float = 0.0):
        self.model_path = model_path
        self.confidence_threshold = confidence_threshold
        self._processor: Any = None
        self._model: Any = None
        self._device: Any = None
        self._id2label: Dict[int, str] = {}
        self._canonical_model_dir: Optional[Path] = None

    @classmethod
    def get_instance(
        cls, model_path: str = "", confidence_threshold: float = 0.0
    ) -> "DocumentLayoutAnalyzer":
        if cls._instance is None:
            cls._instance = cls(model_path=model_path, confidence_threshold=confidence_threshold)
        return cls._instance

    @staticmethod
    def is_available() -> bool:
        analyzer = DocumentLayoutAnalyzer()
        try:
            analyzer._ensure_model()
            return True
        except Exception:
            return False

    def get_setup_error(self) -> str:
        try:
            self._ensure_model()
            return ""
        except Exception as exc:
            return str(exc)

    def _ensure_model(self) -> None:
        if not HAS_PYMUPDF:
            raise RuntimeError("PyMuPDF is required for PDF analysis")
        if not HAS_LAYOUTLM:
            raise RuntimeError(
                "LayoutLMv3 dependencies missing. Install torch and transformers "
                "(see backend/requirements.txt)."
            )
        if self._model is not None:
            return

        raw_dir = resolve_layoutlm_model_dir(self.model_path)
        if not raw_dir.is_dir():
            raise RuntimeError(f"LayoutLM model directory not found: {raw_dir}")

        self._canonical_model_dir = ensure_hf_model_layout(raw_dir)
        logger.info("Loading LayoutLMv3 from %s", self._canonical_model_dir)

        self._processor = LayoutLMv3Processor.from_pretrained(
            str(self._canonical_model_dir),
            apply_ocr=False,
        )
        self._model = LayoutLMv3ForTokenClassification.from_pretrained(
            str(self._canonical_model_dir)
        )
        self._model.eval()
        self._device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self._model.to(self._device)

        config_labels = getattr(self._model.config, "id2label", None) or {}
        self._id2label = {int(k): str(v) for k, v in config_labels.items()}

    @staticmethod
    def _normalize_bbox_pdf(
        bbox: Tuple[float, float, float, float],
        page_width: float,
        page_height: float,
    ) -> Tuple[int, int, int, int]:
        x0, y0, x1, y1 = bbox
        if page_width <= 0 or page_height <= 0:
            return (0, 0, 0, 0)
        return (
            int(max(0.0, min(1000.0, (x0 / page_width) * 1000.0))),
            int(max(0.0, min(1000.0, (y0 / page_height) * 1000.0))),
            int(max(0.0, min(1000.0, (x1 / page_width) * 1000.0))),
            int(max(0.0, min(1000.0, (y1 / page_height) * 1000.0))),
        )

    @staticmethod
    def _normalize_bbox_odl(
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
    def _collect_page_font_sizes(page: "fitz.Page") -> List[float]:
        sizes: List[float] = []
        try:
            for block in page.get_text("dict").get("blocks", []):
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        size = span.get("size")
                        if size:
                            sizes.append(float(size))
        except Exception:
            pass
        return sizes

    @staticmethod
    def _font_size_to_heading_level(size: float, page_sizes: List[float]) -> int:
        if not page_sizes:
            return 2
        tiers = sorted(set(page_sizes), reverse=True)[:6]
        closest = min(tiers, key=lambda tier: abs(tier - size))
        rank = tiers.index(closest)
        return max(1, min(6, rank + 1))

    def _label_to_tag(
        self,
        label: str,
        font_size: Optional[float],
        page_font_sizes: List[float],
    ) -> Tuple[str, Optional[int]]:
        base = LABEL_TO_TAG.get(label, "P")
        if label == "Title":
            return "H1", 1
        if label == "Section-header":
            level = self._font_size_to_heading_level(font_size or 12.0, page_font_sizes)
            return f"H{level}", level
        if base.startswith("H") and len(base) == 2 and base[1].isdigit():
            return base, int(base[1])
        return base, None

    def _extract_words(self, page: "fitz.Page") -> List[Dict[str, Any]]:
        words: List[Dict[str, Any]] = []
        for item in page.get_text("words"):
            x0, y0, x1, y1, text = item[0], item[1], item[2], item[3], item[4]
            text = str(text).strip()
            if not text:
                continue
            words.append(
                {
                    "text": text,
                    "bbox_pdf": (float(x0), float(y0), float(x1), float(y1)),
                }
            )
        return words

    def _predict_word_labels(
        self,
        page: "fitz.Page",
        words: List[Dict[str, Any]],
    ) -> List[WordPrediction]:
        if not words:
            return []

        page_w = page.rect.width
        page_h = page.rect.height
        page_font_sizes = self._collect_page_font_sizes(page)

        pix = page.get_pixmap(dpi=150)
        image = None
        try:
            from PIL import Image
            import io

            image = Image.open(io.BytesIO(pix.tobytes("png")))
        except Exception as exc:
            raise RuntimeError(f"Failed to render page image for LayoutLM: {exc}") from exc

        word_texts = [w["text"] for w in words]
        boxes = [
            list(self._normalize_bbox_pdf(w["bbox_pdf"], page_w, page_h))
            for w in words
        ]

        encoding = self._processor(
            images=image,
            text=word_texts,
            boxes=boxes,
            return_tensors="pt",
            truncation=True,
            padding="max_length",
            max_length=512,
        )
        # Keep BatchEncoding for word_ids(); only tensors go to the model on device.
        word_ids = encoding.word_ids(batch_index=0)
        model_inputs = {k: v.to(self._device) for k, v in encoding.items()}

        with torch.no_grad():
            outputs = self._model(**model_inputs)

        logits = outputs.logits[0]
        probs = torch.softmax(logits, dim=-1)
        predictions = logits.argmax(dim=-1).tolist()
        confidences = probs.max(dim=-1).values.tolist()

        per_word_label: List[Optional[str]] = [None] * len(words)
        per_word_conf: List[float] = [0.0] * len(words)

        for token_idx, word_id in enumerate(word_ids):
            if word_id is None or word_id >= len(words):
                continue
            label_id = predictions[token_idx]
            label = self._id2label.get(label_id, "Text")
            conf = float(confidences[token_idx])
            if per_word_label[word_id] is None or conf > per_word_conf[word_id]:
                per_word_label[word_id] = label
                per_word_conf[word_id] = conf

        predictions_out: List[WordPrediction] = []
        for idx, word in enumerate(words):
            label = per_word_label[idx] or "Text"
            if self.confidence_threshold and per_word_conf[idx] < self.confidence_threshold:
                label = "Text"
            bbox = self._normalize_bbox_pdf(word["bbox_pdf"], page_w, page_h)
            predictions_out.append(
                WordPrediction(
                    text=word["text"],
                    bbox=bbox,
                    label=label,
                    confidence=per_word_conf[idx],
                    font_size=None,
                )
            )

        return predictions_out

    def _group_words_into_blocks(
        self,
        word_predictions: List[WordPrediction],
        page_number: int,
        page_font_sizes: List[float],
    ) -> List[StructureBlock]:
        if not word_predictions:
            return []

        blocks: List[StructureBlock] = []
        current_words: List[WordPrediction] = []
        current_label: Optional[str] = None

        def flush():
            nonlocal current_words, current_label
            if not current_words or not current_label:
                current_words = []
                current_label = None
                return

            font_size = None
            if current_label in {"Title", "Section-header"} and page_font_sizes:
                font_size = max(page_font_sizes)
            tag, heading_level = self._label_to_tag(current_label, font_size, page_font_sizes)
            avg_conf = sum(w.confidence for w in current_words) / len(current_words)
            block = StructureBlock(
                tag=tag,
                page_number=page_number,
                heading_level=heading_level,
                content=" ".join(w.text for w in current_words).strip(),
                words=list(current_words),
                metadata={
                    "source_label": current_label,
                    "confidence": round(avg_conf, 4),
                },
            )
            block.compute_bbox()
            blocks.append(block)
            current_words = []
            current_label = None

        for word in word_predictions:
            if current_label is None:
                current_label = word.label
                current_words = [word]
                continue
            if word.label != current_label:
                flush()
                current_label = word.label
                current_words = [word]
            else:
                current_words.append(word)

        flush()
        return blocks

    def analyze_page(self, page: "fitz.Page", page_number: int = 0) -> PageLayout:
        self._ensure_model()
        page_w = page.rect.width
        page_h = page.rect.height
        words = self._extract_words(page)
        word_predictions = self._predict_word_labels(page, words)
        page_font_sizes = self._collect_page_font_sizes(page)
        blocks = self._group_words_into_blocks(word_predictions, page_number, page_font_sizes)

        return PageLayout(
            page_number=page_number,
            width=page_w,
            height=page_h,
            blocks=blocks,
            word_predictions=word_predictions,
        )

    def analyze_document(self, file_path: Path) -> List[PageLayout]:
        self._ensure_model()
        doc = fitz.open(str(file_path))
        layouts: List[PageLayout] = []
        try:
            total = len(doc)
            for page_index in range(total):
                if page_index % 10 == 0 or page_index == total - 1:
                    logger.info("LayoutLM analyzing page %s/%s", page_index + 1, total)
                layouts.append(self.analyze_page(doc[page_index], page_index))
        finally:
            doc.close()

        total_blocks = sum(len(layout.blocks) for layout in layouts)
        logger.info(
            "LayoutLM analysis complete: %s pages, %s structure blocks",
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

    # ------------------------------------------------------------------
    # OpenDataLoader JSON helpers (kept for unit tests / optional tooling)
    # ------------------------------------------------------------------

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
        normalized_bbox = DocumentLayoutAnalyzer._normalize_bbox_odl(
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
            content=DocumentLayoutAnalyzer._extract_text(element),
            metadata={
                "source_type": raw_type,
                "source_id": element.get("id"),
                "page_width": page_width,
                "page_height": page_height,
                "raw_bbox": bbox,
            },
        )

    @classmethod
    def parse_opendataloader_json(
        cls,
        json_data: Dict[str, Any],
        page_sizes: List[Tuple[float, float]],
    ) -> List[PageLayout]:
        from .opendataloader_layout import OpenDataLoaderLayoutAnalyzer

        return OpenDataLoaderLayoutAnalyzer.parse_opendataloader_json(json_data, page_sizes)
