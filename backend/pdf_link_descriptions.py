"""Supply annotation descriptions from document evidence, never generic labels."""
from pathlib import Path

import fitz
import pikepdf


def _meaningful(value):
    text = " ".join(str(value or "").split())
    if not text or "\ufffd" in text or text.lower() in {
        "link", "hyperlink", "[link requires description]", "[image requires alt text]",
    }:
        return ""
    return text


def _link_alternatives(root):
    """Map OBJR targets to explicitly supplied Link alternatives."""
    descriptions = {}
    visited = set()

    def visit(node, alternative=""):
        if isinstance(node, pikepdf.Array):
            for child in node:
                visit(child, alternative)
            return
        if not isinstance(node, pikepdf.Dictionary):
            return
        identity = node.objgen
        if identity != (0, 0):
            if identity in visited:
                return
            visited.add(identity)
        if str(node.get("/S", "")) == "/Link":
            alternative = _meaningful(node.get("/Alt", ""))
        elif "/S" in node:
            alternative = ""
        if str(node.get("/Type", "")) == "/OBJR" and alternative:
            target = node.get("/Obj")
            if target is not None and target.objgen != (0, 0):
                descriptions[target.objgen] = alternative
        if "/K" in node:
            visit(node.K, alternative)

    visit(root)
    return descriptions


def _word_inside_annotation(box, word):
    rectangle = fitz.Rect(word[:4])
    # Annotation rectangles often cover glyph ink rather than the font's full
    # ascender/descender box. Require the complete word horizontally and at
    # least three quarters vertically; adjacent line fringes are excluded.
    return (box.x0 - 0.01 <= rectangle.x0 and rectangle.x1 <= box.x1 + 0.01
            and rectangle.height > 0
            and (rectangle & box).height >= 0.75 * rectangle.height
            and box.y0 <= (rectangle.y0 + rectangle.y1) / 2 <= box.y1)


def _visible_label(box, raw_text):
    lines = []
    for block in raw_text.get("blocks", []):
        for line in block.get("lines", []):
            characters = [character for span in line.get("spans", [])
                          for character in span.get("chars", [])]
            selected = [index for index, character in enumerate(characters)
                        if _word_inside_annotation(box, character["bbox"])]
            if selected:
                first, last = selected[0], selected[-1]
                # A clipped alphanumeric word is insufficient label evidence.
                if ((first > 0 and characters[first - 1]["c"].isalnum()
                     and characters[first]["c"].isalnum())
                    or (last + 1 < len(characters) and characters[last + 1]["c"].isalnum()
                        and characters[last]["c"].isalnum())):
                    continue
            text = "".join(characters[index]["c"] for index in selected)
            if text.strip():
                lines.append(text)
    return _meaningful(" ".join(lines))


def repair_link_descriptions(pdf_path: Path):
    repaired = unresolved = 0
    labels = {}
    # Close the renderer before opening the overwrite writer on Windows.
    with fitz.open(str(pdf_path)) as document, pikepdf.open(pdf_path) as source:
        alternatives = _link_alternatives(source.Root.get("/StructTreeRoot", pikepdf.Dictionary()))
        for page_index, page in enumerate(source.pages):
            raw_text = None
            for annotation_index, annotation in enumerate(page.obj.get("/Annots", [])):
                if str(annotation.get("/Subtype", "")) != "/Link":
                    continue
                if _meaningful(annotation.get("/Contents", "")):
                    continue
                label = alternatives.get(annotation.objgen, "")
                if not label:
                    rect = annotation.get("/Rect")
                    if rect is not None and len(rect) == 4:
                        if raw_text is None:
                            raw_text = document[page_index].get_text("rawdict")
                        box = fitz.Rect(*map(float, rect)) * document[page_index].transformation_matrix
                        label = _visible_label(box, raw_text)
                labels[(page_index, annotation_index)] = label
    with pikepdf.open(pdf_path, allow_overwriting_input=True) as pdf:
        for page_index, page in enumerate(pdf.pages):
            for annotation_index, annotation in enumerate(page.obj.get("/Annots", [])):
                key = (page_index, annotation_index)
                if key not in labels:
                    continue
                label = labels[key]
                if label:
                    annotation.Contents = pikepdf.String(label)
                    repaired += 1
                else:
                    unresolved += 1
        if repaired:
            pdf.save(pdf_path)
    return {"issue_id": "pdf-link-descriptions", "success": unresolved == 0,
            "message": f"Described {repaired} link annotation(s); {unresolved} require semantic review",
            "new_value": f"{repaired} descriptions", "unresolved": unresolved}
