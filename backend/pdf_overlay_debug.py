"""
Block-level overlay debug images.

Renders each PDF page as an image then draws coloured rectangles for every
StructureBlock extracted from the PDF layout, annotated with:
  - tag  (e.g. H1, P, Table, Figure)
  - first ~40 characters of block text

Output is a ZIP of page_001.png, page_002.png, ... plus tag_summary.json.
"""
import json
import logging
import zipfile
from pathlib import Path
from typing import List, Dict

logger = logging.getLogger(__name__)

try:
    import fitz  # PyMuPDF
    HAS_PYMUPDF = True
except ImportError:
    HAS_PYMUPDF = False

try:
    from PIL import Image, ImageDraw, ImageFont
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

from .layout_model import PageLayout, StructureBlock

TAG_COLORS: Dict[str, str] = {
    "H1": "#ef4444",
    "H2": "#f97316",
    "H3": "#eab308",
    "H4": "#84cc16",
    "H5": "#22c55e",
    "H6": "#14b8a6",
    "P": "#3b82f6",
    "L": "#8b5cf6",
    "LI": "#a78bfa",
    "Table": "#ec4899",
    "Figure": "#f43f5e",
    "Caption": "#06b6d4",
    "Note": "#64748b",
    "Formula": "#d946ef",
    "Span": "#94a3b8",
    "Artifact": "#475569",
}

DEFAULT_COLOR = "#6b7280"
RENDER_DPI = 150


def _hex_to_rgb(hex_color: str):
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
def _get_font(size: int = 12):
    """Try to load a truetype font, fall back to default."""
    try:
        return ImageFont.truetype("arial.ttf", size)
    except Exception:
        try:
            return ImageFont.truetype("DejaVuSans.ttf", size)
        except Exception:
            return ImageFont.load_default()


def build_block_label(block: StructureBlock) -> str:
    """Format the debug label shown on each overlay block."""
    short_text = block.text[:40].replace("\n", " ")
    return f"{block.tag}  {short_text}".strip()


def generate_block_overlays_zip(
    pdf_path: Path,
    layouts: List[PageLayout],
    out_dir: Path,
) -> Path:
    """
    Render overlay PNGs and bundle them into a ZIP.

    Args:
        pdf_path: Path to the source PDF.
        layouts: List[PageLayout] from DocumentLayoutAnalyzer.analyze_document().
        out_dir: Directory where the ZIP will be written.

    Returns:
        Path to the generated ZIP file.
    """
    if not HAS_PYMUPDF:
        raise RuntimeError("PyMuPDF is required for overlay generation")
    if not HAS_PIL:
        raise RuntimeError("Pillow is required for overlay generation")

    out_dir.mkdir(parents=True, exist_ok=True)
    zip_name = f"layout_overlays_{pdf_path.stem}.zip"
    zip_path = out_dir / zip_name

    doc = fitz.open(str(pdf_path))
    font = _get_font(11)
    font_small = _get_font(9)

    tag_summary: Dict[str, int] = {}

    try:
        with zipfile.ZipFile(str(zip_path), "w", zipfile.ZIP_DEFLATED) as zf:
            for layout in layouts:
                page_num = layout.page_number
                if page_num >= len(doc):
                    continue

                page = doc[page_num]
                pix = page.get_pixmap(dpi=RENDER_DPI)
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                draw = ImageDraw.Draw(img, "RGBA")

                px_w = pix.width
                px_h = pix.height

                for block in layout.blocks:
                    tag_summary[block.tag] = tag_summary.get(block.tag, 0) + 1

                    if block.bbox is None:
                        continue

                    x0_n, y0_n, x1_n, y1_n = block.bbox
                    x0 = int(x0_n / 1000 * px_w)
                    y0 = int(y0_n / 1000 * px_h)
                    x1 = int(x1_n / 1000 * px_w)
                    y1 = int(y1_n / 1000 * px_h)

                    color_hex = TAG_COLORS.get(block.tag, DEFAULT_COLOR)
                    rgb = _hex_to_rgb(color_hex)
                    fill_rgba = rgb + (40,)
                    outline_rgba = rgb + (200,)

                    draw.rectangle([x0, y0, x1, y1], fill=fill_rgba, outline=outline_rgba, width=2)

                    label = build_block_label(block)

                    label_y = max(y0 - 14, 0)
                    draw.rectangle(
                        [x0, label_y, x0 + min(len(label) * 6 + 8, px_w - x0), label_y + 14],
                        fill=rgb + (180,),
                    )
                    draw.text((x0 + 3, label_y + 1), label, fill=(255, 255, 255), font=font_small)

                png_name = f"page_{page_num + 1:03d}.png"
                import io
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                zf.writestr(png_name, buf.getvalue())

            zf.writestr("tag_summary.json", json.dumps(tag_summary, indent=2))

    finally:
        doc.close()

    logger.info(f"Generated overlay ZIP: {zip_path} ({len(layouts)} pages)")
    return zip_path
