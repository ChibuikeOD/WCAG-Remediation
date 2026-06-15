"""
Context assembly for AI-generated alt text.

The alt-text model needs more than a crop. These helpers collect a compact,
deterministic context packet from nearby document structure without sending the
entire document.
"""
from __future__ import annotations

import base64
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional

from .models import DocumentImageItem


CAPTION_RE = re.compile(r"((?:Figure|Fig\.?|Table|Chart|Map|Diagram)\s*\d+\.?\s*[^.\n\r]*\.)", re.IGNORECASE)
WHITESPACE_RE = re.compile(r"\s+")


@dataclass
class NeighboringImageContext:
    id: str
    page_num: Optional[int]
    caption: str = ""
    current_alt: str = ""
    image_url: Optional[str] = None


@dataclass
class AltTextContext:
    document_title: str = ""
    file_type: str = ""
    target_image_id: str = ""
    page_num: Optional[int] = None
    context_mode: str = "balanced"
    caption: str = ""
    headings: List[str] = field(default_factory=list)
    page_text: str = ""
    previous_page_text: str = ""
    next_page_text: str = ""
    neighboring_images: List[NeighboringImageContext] = field(default_factory=list)

    def context_used(self) -> dict[str, Any]:
        return {
            "mode": self.context_mode,
            "document_title": bool(self.document_title),
            "headings": len(self.headings),
            "caption": bool(self.caption),
            "page_text": bool(self.page_text),
            "previous_page_text": bool(self.previous_page_text),
            "next_page_text": bool(self.next_page_text),
            "neighboring_images": len(self.neighboring_images),
        }


def normalize_text(text: str) -> str:
    return WHITESPACE_RE.sub(" ", text or "").strip()


def trim_context_text(text: str, max_chars: int) -> str:
    text = normalize_text(text)
    if len(text) <= max_chars:
        return text

    trimmed = text[: max(0, max_chars - 3)].rstrip()
    last_space = trimmed.rfind(" ")
    if last_space > max_chars * 0.6:
        trimmed = trimmed[:last_space]
    return trimmed.rstrip(" ,.;:") + "..."


def _limits(context_mode: str) -> dict[str, int]:
    if context_mode == "minimal":
        return {"page": 900, "adjacent": 0, "neighbors": 0, "heading": 3}
    if context_mode == "maximum":
        return {"page": 3000, "adjacent": 1200, "neighbors": 4, "heading": 8}
    return {"page": 1800, "adjacent": 700, "neighbors": 2, "heading": 5}


def _caption_from_text(text: str) -> str:
    match = CAPTION_RE.search(normalize_text(text))
    return match.group(1).strip() if match else ""


def _neighbors(images: List[DocumentImageItem], target: DocumentImageItem, limit: int) -> List[NeighboringImageContext]:
    if limit <= 0:
        return []
    try:
        target_index = next(i for i, img in enumerate(images) if img.id == target.id)
    except StopIteration:
        return []

    candidates: list[tuple[int, DocumentImageItem]] = []
    for idx, img in enumerate(images):
        if img.id == target.id:
            continue
        candidates.append((abs(idx - target_index), img))

    ordered = [img for _, img in sorted(candidates, key=lambda item: item[0])[:limit]]
    return [
        NeighboringImageContext(
            id=img.id,
            page_num=img.page_num,
            caption=img.caption or "",
            current_alt=img.current_alt or "",
            image_url=img.image_url,
        )
        for img in ordered
    ]


def extract_html_images(html_path: Path) -> List[DocumentImageItem]:
    from bs4 import BeautifulSoup

    with open(html_path, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "html5lib")

    figures: list[DocumentImageItem] = []
    imgs = list(soup.find_all("img"))
    for idx, img in enumerate(imgs):
        src = img.get("src", "")
        alt = img.get("alt", "")
        image_url = src
        if src and not src.startswith(("http://", "https://", "data:")):
            potential_path = html_path.parent / src
            if potential_path.exists():
                try:
                    with open(potential_path, "rb") as img_f:
                        ext = potential_path.suffix.lower().replace(".", "")
                        if ext == "jpg":
                            ext = "jpeg"
                        encoded = base64.b64encode(img_f.read()).decode("utf-8")
                        image_url = f"data:image/{ext};base64,{encoded}"
                except Exception:
                    pass

        caption = ""
        parent_figure = img.find_parent("figure")
        if parent_figure:
            figcaption = parent_figure.find("figcaption")
            if figcaption:
                caption = normalize_text(figcaption.get_text(" "))

        figures.append(
            DocumentImageItem(
                id=f"html_img_{idx}",
                page_num=None,
                current_alt=alt or "",
                image_url=image_url,
                figure_order=idx + 1,
                caption=caption,
            )
        )

    for idx, item in enumerate(figures):
        neighbor_ids = []
        if idx > 0:
            neighbor_ids.append(figures[idx - 1].id)
        if idx < len(figures) - 1:
            neighbor_ids.append(figures[idx + 1].id)
        item.neighbor_image_ids = neighbor_ids

    return figures


def extract_pdf_images(pdf_path: Path) -> List[DocumentImageItem]:
    import fitz
    import pikepdf

    figures: list[DocumentImageItem] = []
    if not pdf_path.exists():
        return figures

    doc = fitz.open(str(pdf_path))
    try:
        with pikepdf.open(pdf_path) as pdf:
            struct_root = pdf.Root.get("/StructTreeRoot")
            if not struct_root:
                for page_idx in range(len(doc)):
                    page = doc[page_idx]
                    img_infos = page.get_image_info(xrefs=True)
                    for img_idx, img_info in enumerate(img_infos):
                        bbox = [float(v) for v in img_info["bbox"]]
                        width_ratio = (bbox[2] - bbox[0]) / page.rect.width
                        height_ratio = (bbox[3] - bbox[1]) / page.rect.height
                        if width_ratio > 0.95 and height_ratio > 0.95:
                            continue

                        image_url = _render_pdf_crop(page, bbox, dpi=100)
                        page_text = normalize_text(page.get_text("text"))
                        figures.append(
                            DocumentImageItem(
                                id=f"raw_page_{page_idx}_img_{img_idx}_xref_{img_info['xref']}",
                                page_num=page_idx + 1,
                                current_alt="",
                                image_url=image_url,
                                figure_order=len(figures) + 1,
                                bbox=bbox,
                                caption=_caption_from_text(page_text),
                                nearby_text=trim_context_text(page_text, 500),
                            )
                        )
                _attach_neighbor_ids(figures)
                return figures

            def walk(node: Any, path: list[int]) -> None:
                if not hasattr(node, "keys"):
                    return

                if "/S" in node and str(node["/S"]) == "/Figure":
                    current_alt = str(node["/Alt"]) if "/Alt" in node else ""
                    page_num = 0
                    page_obj = node.get("/Pg")
                    if page_obj:
                        try:
                            page_num = pdf.pages.index(page_obj)
                        except Exception:
                            pass

                    bbox = _pdf_bbox_from_node(node)
                    if not bbox:
                        bbox = _pdf_bbox_from_objr(node, doc, page_num)

                    if not _is_full_page_figure(doc, page_num, bbox):
                        page = doc[page_num]
                        image_url = _render_pdf_crop(page, _to_fitz_bbox(page, bbox) if bbox else None, dpi=120)
                        page_text = normalize_text(page.get_text("text"))
                        figures.append(
                            DocumentImageItem(
                                id="-".join(map(str, path)),
                                page_num=page_num + 1,
                                current_alt=current_alt,
                                image_url=image_url,
                                figure_order=len(figures) + 1,
                                bbox=bbox,
                                caption=_caption_from_text(page_text),
                                nearby_text=trim_context_text(page_text, 500),
                            )
                        )

                if "/K" in node:
                    kids = node["/K"]
                    if not isinstance(kids, pikepdf.Array):
                        kids = [kids]
                    for idx, kid in enumerate(kids):
                        walk(kid, path + [idx])

            walk(struct_root, [])
    finally:
        doc.close()

    _attach_neighbor_ids(figures)
    return figures


def build_alt_text_context(
    document_path: Path,
    file_type: str,
    images: List[DocumentImageItem],
    target_image: DocumentImageItem,
    context_mode: str = "balanced",
) -> AltTextContext:
    limits = _limits(context_mode)
    if file_type == "html":
        return _build_html_context(document_path, images, target_image, context_mode, limits)
    if file_type == "pdf":
        return _build_pdf_context(document_path, images, target_image, context_mode, limits)
    return AltTextContext(file_type=file_type, target_image_id=target_image.id, context_mode=context_mode)


def _build_html_context(
    html_path: Path,
    images: List[DocumentImageItem],
    target_image: DocumentImageItem,
    context_mode: str,
    limits: dict[str, int],
) -> AltTextContext:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html_path.read_text(encoding="utf-8"), "html5lib")
    imgs = list(soup.find_all("img"))
    index = _image_index(images, target_image)
    target_node = imgs[index] if 0 <= index < len(imgs) else None
    parent = target_node.find_parent("figure") if target_node else None

    caption = target_image.caption or ""
    if not caption and parent:
        figcaption = parent.find("figcaption")
        caption = normalize_text(figcaption.get_text(" ")) if figcaption else ""

    title = normalize_text(soup.title.get_text(" ")) if soup.title else ""
    headings = [normalize_text(h.get_text(" ")) for h in soup.find_all(["h1", "h2", "h3"])][: limits["heading"]]
    local_text = _html_local_text(target_node, parent)
    if not local_text:
        local_text = normalize_text(soup.body.get_text(" ") if soup.body else soup.get_text(" "))

    return AltTextContext(
        document_title=title,
        file_type="html",
        target_image_id=target_image.id,
        page_num=None,
        context_mode=context_mode,
        caption=caption,
        headings=headings,
        page_text=trim_context_text(local_text, limits["page"]),
        neighboring_images=_neighbors(images, target_image, limits["neighbors"]),
    )


def _build_pdf_context(
    pdf_path: Path,
    images: List[DocumentImageItem],
    target_image: DocumentImageItem,
    context_mode: str,
    limits: dict[str, int],
) -> AltTextContext:
    import fitz

    doc = fitz.open(str(pdf_path))
    try:
        page_idx = max(0, min((target_image.page_num or 1) - 1, len(doc) - 1))
        page = doc[page_idx]
        metadata_title = normalize_text((doc.metadata or {}).get("title") or "")
        page_text = normalize_text(page.get_text("text"))
        previous_text = ""
        next_text = ""
        if limits["adjacent"] and page_idx > 0:
            previous_text = trim_context_text(doc[page_idx - 1].get_text("text"), limits["adjacent"])
        if limits["adjacent"] and page_idx + 1 < len(doc):
            next_text = trim_context_text(doc[page_idx + 1].get_text("text"), limits["adjacent"])

        caption = target_image.caption or _caption_from_text(page_text)
        headings = _pdf_heading_candidates(page)

        return AltTextContext(
            document_title=metadata_title,
            file_type="pdf",
            target_image_id=target_image.id,
            page_num=target_image.page_num,
            context_mode=context_mode,
            caption=caption,
            headings=headings[: limits["heading"]],
            page_text=trim_context_text(page_text, limits["page"]),
            previous_page_text=previous_text,
            next_page_text=next_text,
            neighboring_images=_neighbors(images, target_image, limits["neighbors"]),
        )
    finally:
        doc.close()


def _html_local_text(target_node: Any, parent: Any) -> str:
    parts: list[str] = []
    if parent:
        parts.append(parent.get_text(" "))
        previous = [
            sibling.get_text(" ")
            for sibling in parent.find_previous_siblings()
            if getattr(sibling, "name", None) in {"p", "h1", "h2", "h3", "figure"}
        ][:2]
        for text in reversed(previous):
            parts.insert(0, text)
        following = [
            sibling.get_text(" ")
            for sibling in parent.find_next_siblings()
            if getattr(sibling, "name", None) in {"p", "h1", "h2", "h3", "figure"}
        ][:2]
        parts.extend(following)
    elif target_node:
        for sibling in list(target_node.previous_siblings)[-2:]:
            if hasattr(sibling, "get_text"):
                parts.insert(0, sibling.get_text(" "))
        for sibling in list(target_node.next_siblings)[:2]:
            if hasattr(sibling, "get_text"):
                parts.append(sibling.get_text(" "))
    return normalize_text(" ".join(parts))


def _image_index(images: List[DocumentImageItem], target_image: DocumentImageItem) -> int:
    for idx, img in enumerate(images):
        if img.id == target_image.id:
            return idx
    return -1


def _attach_neighbor_ids(figures: list[DocumentImageItem]) -> None:
    for idx, item in enumerate(figures):
        ids = []
        if idx > 0:
            ids.append(figures[idx - 1].id)
        if idx < len(figures) - 1:
            ids.append(figures[idx + 1].id)
        item.neighbor_image_ids = ids


def _render_pdf_crop(page: Any, bbox: Optional[list[float]], dpi: int) -> Optional[str]:
    try:
        import fitz

        if bbox:
            rect = page.rect & fitz_rect(bbox)
            if rect.is_empty or rect.width < 5 or rect.height < 5:
                pix = page.get_pixmap(dpi=72)
            else:
                pix = page.get_pixmap(clip=rect, dpi=dpi)
        else:
            pix = page.get_pixmap(dpi=50)
        if pix.alpha:
            pix = fitz.Pixmap(pix, 0)
        img_bytes = pix.tobytes("png")
        return f"data:image/png;base64,{base64.b64encode(img_bytes).decode('utf-8')}"
    except Exception:
        return None


def fitz_rect(bbox: list[float]) -> Any:
    import fitz

    return fitz.Rect(float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]))


def _pdf_bbox_from_node(node: Any) -> Optional[list[float]]:
    attr = node.get("/A") if hasattr(node, "get") else None
    if hasattr(attr, "keys") and "/BBox" in attr:
        return [float(x) for x in attr["/BBox"]]
    return None


def _pdf_bbox_from_objr(node: Any, doc: Any, page_num: int) -> Optional[list[float]]:
    import pikepdf

    if "/K" not in node:
        return None
    kids = node["/K"]
    if not isinstance(kids, pikepdf.Array):
        kids = [kids]
    for kid in kids:
        if hasattr(kid, "keys") and "/Type" in kid and str(kid["/Type"]) == "/OBJR":
            obj = kid.get("/Obj")
            if not obj:
                continue
            xref = obj.objgen[0]
            page = doc[page_num]
            for img_info in page.get_image_info(xrefs=True):
                if img_info["xref"] == xref:
                    return [float(v) for v in img_info["bbox"]]
    return None


def _to_fitz_bbox(page: Any, bbox: Optional[list[float]]) -> Optional[list[float]]:
    if not bbox:
        return None
    x0 = max(0, min(bbox[0], page.rect.width))
    y0 = max(0, min(bbox[1], page.rect.height))
    x1 = max(0, min(bbox[2], page.rect.width))
    y1 = max(0, min(bbox[3], page.rect.height))
    return [x0, y0, x1, y1]


def _is_full_page_figure(doc: Any, page_num: int, bbox: Optional[list[float]]) -> bool:
    if not bbox:
        return False
    try:
        page = doc[page_num]
        width_ratio = (bbox[2] - bbox[0]) / page.rect.width
        height_ratio = (bbox[3] - bbox[1]) / page.rect.height
        return width_ratio > 0.95 and height_ratio > 0.95
    except Exception:
        return False


def _pdf_heading_candidates(page: Any) -> list[str]:
    blocks = page.get_text("dict").get("blocks", [])
    candidates: list[tuple[float, str]] = []
    for block in blocks:
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            text = normalize_text(" ".join(span.get("text", "") for span in spans))
            if not text:
                continue
            max_size = max((span.get("size", 0) for span in spans), default=0)
            if max_size >= 12 or text.istitle():
                candidates.append((max_size, text))
    return [text for _, text in sorted(candidates, key=lambda item: item[0], reverse=True)]
