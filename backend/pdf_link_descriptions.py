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


def repair_link_descriptions(pdf_path: Path):
    repaired = unresolved = 0
    # Close the renderer before opening the overwrite writer on Windows.
    with fitz.open(str(pdf_path)) as document:
        page_evidence = [(page.transformation_matrix, page.get_text("words")) for page in document]
    with pikepdf.open(pdf_path, allow_overwriting_input=True) as pdf:
        alternatives = _link_alternatives(pdf.Root.get("/StructTreeRoot", pikepdf.Dictionary()))
        for page_index, page in enumerate(pdf.pages):
            matrix, words = page_evidence[page_index]
            for annotation in page.obj.get("/Annots", []):
                if str(annotation.get("/Subtype", "")) != "/Link":
                    continue
                if _meaningful(annotation.get("/Contents", "")):
                    continue
                label = alternatives.get(annotation.objgen, "")
                if not label:
                    rect = annotation.get("/Rect")
                    if rect is not None and len(rect) == 4:
                        box = fitz.Rect(*map(float, rect)) * matrix
                        # Require complete words inside the clickable region.
                        selected = [word for word in words if box.contains(fitz.Rect(word[:4]))]
                        selected.sort(key=lambda word: (word[5], word[6], word[7]))
                        label = _meaningful(" ".join(word[4] for word in selected))
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
