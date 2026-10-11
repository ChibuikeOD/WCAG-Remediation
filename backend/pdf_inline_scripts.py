"""Conservative inline script associations from rendered text geometry.

Typography is evidence of an inline relationship, not of Reference or Formula
semantics. No text, drawing operator, or Unicode mapping is rewritten here.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import floor, hypot
import unicodedata

import fitz


@dataclass(frozen=True)
class ScriptRun:
    text: str
    kind: str
    bbox: tuple[float, float, float, float]
    base_origin: tuple[float, float]
    base_text: str


def _unicode_script(char: str) -> str | None:
    name = unicodedata.name(char, "")
    if name.startswith("SUPERSCRIPT"):
        return "superscript"
    if "SUBSCRIPT" in name:
        return "subscript"
    return None


def detect_script_runs(page) -> list[ScriptRun]:
    """Associate horizontal script glyphs with a nearby preceding base glyph.

    Use effective font size, baseline displacement and horizontal proximity
    together, across text objects. Large offsets and rotations are deliberately
    left for review. The bounded predecessor window avoids a page-wide median
    and uses a spatial index rather than trusting text-object drawing order.
    """
    glyphs = []
    # get_texttrace() alone reproducibly corrupts native shutdown on the
    # 209-page D10 input with the supported PyMuPDF runtime. Raw text keeps
    # per-character origins, effective font sizes and line direction without
    # creating that trace device. Exclude image payloads from this inventory.
    raw = page.get_text("rawdict", flags=fitz.TEXTFLAGS_RAWDICT & ~fitz.TEXT_PRESERVE_IMAGES)
    for block in raw.get("blocks", ()):
        if block.get("type", 0) != 0:
            continue
        for line in block.get("lines", ()):
            direction = line.get("dir", (1.0, 0.0))
            if hypot(direction[0] - 1.0, direction[1]) > 0.01:
                continue
            for span in line.get("spans", ()):
                size = float(span.get("size", 0))
                if size <= 0:
                    continue
                for char in span.get("chars", ()):
                    text = char.get("c", "")
                    if len(text) != 1:
                        continue
                    glyphs.append((text, tuple(char["origin"]), tuple(char["bbox"]), size))

    grid = {}
    for index, glyph in enumerate(glyphs):
        box, origin = glyph[2], glyph[1]
        grid.setdefault((floor(box[2] / 16), floor(origin[1] / 16)), []).append(index)
    matches = []
    roots = {}
    for index in sorted(range(len(glyphs)), key=lambda i: glyphs[i][2][0]):
        char, origin, bbox, size = glyphs[index]
        if char.isspace():
            continue
        candidates = []
        nearby = []
        reach = max(1, int(size / 16) + 1)
        cell_x, cell_y = floor(bbox[0] / 16), floor(origin[1] / 16)
        for gx in range(cell_x - reach, cell_x + reach + 1):
            for gy in range(cell_y - reach, cell_y + reach + 1):
                nearby.extend(grid.get((gx, gy), ()))
        for prev in nearby:
            if prev == index or glyphs[prev][2][0] >= bbox[0]:
                continue
            base_char, base_origin, base_bbox, base_size = glyphs[prev]
            if base_char.isspace():
                continue
            gap = bbox[0] - base_bbox[2]
            if not -0.15 * base_size <= gap <= 0.45 * base_size:
                continue
            root = roots.get(prev, prev)
            root_char, root_origin, _root_bbox, root_size = glyphs[root]
            delta = origin[1] - root_origin[1]
            unicode_kind = _unicode_script(char)
            if unicode_kind:
                if abs(delta) > 0.65 * root_size or size > 1.05 * root_size:
                    continue
                kind = unicode_kind
            else:
                if not 0.12 * root_size <= abs(delta) <= 0.65 * root_size:
                    continue
                if not 0.45 * root_size <= size <= 1.05 * root_size:
                    continue
                kind = "superscript" if delta < 0 else "subscript"
            candidates.append((abs(gap), prev, root, kind))
        if candidates:
            _gap, _prev, root, kind = min(candidates)
            roots[index] = root
            matches.append((index, root, kind))

    by_root = {}
    for index, root, kind in matches:
        by_root.setdefault((root, kind), []).append(index)
    groups = [(sorted(indices, key=lambda i: glyphs[i][2][0]), root, kind)
              for (root, kind), indices in by_root.items()]
    runs = []
    for indices, root, kind in groups:
        boxes = [glyphs[index][2] for index in indices]
        runs.append(ScriptRun(
            text="".join(glyphs[index][0] for index in indices), kind=kind,
            bbox=(min(b[0] for b in boxes), min(b[1] for b in boxes),
                  max(b[2] for b in boxes), max(b[3] for b in boxes)),
            base_origin=glyphs[root][1], base_text=glyphs[root][0],
        ))
    return runs


def associate_script_blocks(page, layout) -> int:
    """Absorb an isolated script block into its existing inline parent.

    Only whole-block exact text matches qualify. Headings, artifacts, notes,
    tables and explicitly classified references retain their own semantics.
    Coordinates supplied to the native tagger include the attached script.
    """
    eligible = {"P", "Formula", "Caption"}
    removed = set()
    count = 0
    for run in detect_script_runs(page):
        x, y = run.base_origin
        sx0, sy0, sx1, sy1 = run.bbox
        candidates = []
        for idx, block in enumerate(layout.blocks):
            raw = block.metadata.get("raw_bbox")
            if idx in removed or block.tag not in eligible or not raw:
                continue
            left, bottom, right, top = raw
            if left - 1 <= x <= right + 1 and bottom - 1 <= layout.height - y <= top + 1:
                candidates.append(((right - left) * (top - bottom), idx))
        if not candidates:
            continue
        _area, parent_idx = min(candidates)
        parent = layout.blocks[parent_idx]
        parent.metadata.setdefault("inline_scripts", []).append({
            "text": run.text, "kind": run.kind, "base_text": run.base_text,
            "bbox": list(run.bbox), "base_origin": list(run.base_origin),
        })
        for idx, block in enumerate(layout.blocks):
            raw = block.metadata.get("raw_bbox")
            if (idx == parent_idx or idx in removed or block.tag not in {"P", "Reference"} or not raw
                    or block.text.strip() != run.text.strip()
                    or block.metadata.get("table_id")):
                continue
            left, bottom, right, top = raw
            # Require real overlap with the detected glyphs; equal footnote
            # numbering elsewhere on the page is insufficient.
            if min(right, sx1) <= max(left, sx0) or min(top, layout.height - sy0) <= max(bottom, layout.height - sy1):
                continue
            p = parent.metadata["raw_bbox"]
            parent.metadata["raw_bbox"] = [min(p[0], left), min(p[1], bottom),
                                           max(p[2], right), max(p[3], top)]
            if block.tag == "Reference":
                group = f"inline-p{getattr(layout, 'page_number', 0)}-b{parent_idx}"
                parent.metadata["inline_group_id"] = group
                block.metadata["inline_parent_id"] = group
                continue
            removed.add(idx)
            count += 1
    layout.blocks = [block for idx, block in enumerate(layout.blocks) if idx not in removed]
    return count


def inline_order_hints(runs, page_height):
    """Return explicit baseline hints and count ambiguous stacked pairs.

    Nearly aligned sub/superscripts do not establish their semantic sequence.
    Keep those baselines in authored order for human review.
    """
    ambiguous = set()
    for run in runs:
        for other in runs:
            if (run["kind"] != other["kind"] and run["base_origin"] == other["base_origin"]
                    and abs(run["bbox"][0] - other["bbox"][0]) <= 1.0):
                ambiguous.add(tuple(run["base_origin"]))
    hints = []
    for run in runs:
        if tuple(run["base_origin"]) in ambiguous:
            continue
        x0, y0, x1, y1 = run["bbox"]
        bx, by = run["base_origin"]
        hints.append(",".join(str(v) for v in (x0, page_height - y1, x1, page_height - y0, bx, page_height - by)))
    return ";".join(hints), len(ambiguous)
