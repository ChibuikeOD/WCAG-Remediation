"""Detect and repair incomplete PDF ToUnicode character maps."""
from __future__ import annotations

from dataclasses import dataclass
import base64
from io import BytesIO
from pathlib import Path
import os
import re
from statistics import median
import tempfile
from typing import Iterable, Optional

import fitz
from fontTools import agl
from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw
import pikepdf


_PAIR_RE = re.compile(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>")
_BFCHAR_RE = re.compile(rb"\d+\s+beginbfchar(.*?)endbfchar", re.DOTALL)
_BFRANGE_RE = re.compile(rb"\d+\s+beginbfrange(.*?)endbfrange", re.DOTALL)
_CODESPACE_RE = re.compile(rb"\d+\s+begincodespacerange(.*?)endcodespacerange", re.DOTALL)


@dataclass(frozen=True)
class TextOccurrence:
    page_number: int
    font_objgen: tuple[int, int]
    resource_name: str
    cid: int


@dataclass(frozen=True)
class MissingUnicodeFinding:
    font_objgen: tuple[int, int]
    base_font: str
    cid: int
    gid: Optional[int]
    occurrences: tuple[TextOccurrence, ...]

    @property
    def occurrence_count(self) -> int:
        return len(self.occurrences)

    @property
    def pages(self) -> tuple[int, ...]:
        return tuple(sorted({item.page_number for item in self.occurrences}))


@dataclass(frozen=True)
class ParsedToUnicode:
    code_width: int
    mappings: dict[int, str]


@dataclass(frozen=True)
class FontEvidence:
    unicode_by_gid: dict[int, tuple[str, ...]]
    glyph_name_by_gid: dict[int, str]
    unicode_by_glyph_name: dict[str, str]


@dataclass(frozen=True)
class DeterministicResolution:
    text: str
    evidence: tuple[str, ...]


def resolve_deterministically(
    finding: MissingUnicodeFinding, evidence: FontEvidence
) -> Optional[DeterministicResolution]:
    """Resolve only when every authoritative font signal agrees."""
    if finding.gid is None:
        return None
    candidates: dict[str, set[str]] = {}
    cmap_values = evidence.unicode_by_gid.get(finding.gid, ())
    for value in cmap_values:
        candidates.setdefault(value, set()).add("font-cmap")
    glyph_name = evidence.glyph_name_by_gid.get(finding.gid)
    if glyph_name:
        value = evidence.unicode_by_glyph_name.get(glyph_name)
        if value:
            candidates.setdefault(value, set()).add("glyph-name")
    if len(candidates) != 1:
        return None
    text, sources = next(iter(candidates.items()))
    return DeterministicResolution(text=text, evidence=tuple(sorted(sources)))


def collect_font_evidence(
    pdf_path: Path, finding: MissingUnicodeFinding
) -> FontEvidence:
    """Collect authoritative Unicode and glyph-name evidence from an embedded font."""
    unicode_by_gid: dict[int, set[str]] = {}
    glyph_name_by_gid: dict[int, str] = {}
    unicode_by_glyph_name: dict[str, str] = {}
    with pikepdf.open(pdf_path) as pdf:
        try:
            font = pdf.get_object(finding.font_objgen)
            descendant = font.get("/DescendantFonts", [])[0]
            descriptor = descendant.get("/FontDescriptor")
            font_stream = None
            if descriptor:
                for key in ("/FontFile2", "/FontFile3", "/FontFile"):
                    candidate = descriptor.get(key)
                    if isinstance(candidate, pikepdf.Stream):
                        font_stream = candidate
                        break
            if font_stream is None:
                return FontEvidence({}, {}, {})
            ttfont = TTFont(BytesIO(font_stream.read_bytes()), lazy=False)
        except Exception:
            return FontEvidence({}, {}, {})

    glyph_order = ttfont.getGlyphOrder()
    name_to_gid = {name: index for index, name in enumerate(glyph_order)}
    glyph_name_by_gid = {index: name for index, name in enumerate(glyph_order)}
    if "cmap" in ttfont:
        for table in ttfont["cmap"].tables:
            if not table.isUnicode():
                continue
            for codepoint, glyph_name in table.cmap.items():
                gid = name_to_gid.get(glyph_name)
                if gid is not None:
                    unicode_by_gid.setdefault(gid, set()).add(chr(codepoint))
    for glyph_name in glyph_order:
        try:
            value = agl.toUnicode(glyph_name)
        except Exception:
            value = ""
        if value:
            unicode_by_glyph_name[glyph_name] = value
    ttfont.close()
    return FontEvidence(
        unicode_by_gid={gid: tuple(sorted(values)) for gid, values in unicode_by_gid.items()},
        glyph_name_by_gid=glyph_name_by_gid,
        unicode_by_glyph_name=unicode_by_glyph_name,
    )


def _png_data_url(image: Image.Image) -> str:
    output = BytesIO()
    image.save(output, format="PNG")
    return "data:image/png;base64," + base64.b64encode(output.getvalue()).decode("ascii")


def _render_crop(
    page: fitz.Page,
    clip: fitz.Rect,
    *,
    dpi: int,
    target: Optional[fitz.Rect] = None,
) -> str:
    clip = clip & page.rect
    pix = page.get_pixmap(clip=clip, dpi=dpi, alpha=False)
    image = Image.open(BytesIO(pix.tobytes("png"))).convert("RGB")
    if target is not None:
        scale = dpi / 72.0
        left = int((target.x0 - clip.x0) * scale) - 3
        top = int((target.y0 - clip.y0) * scale) - 3
        right = int((target.x1 - clip.x0) * scale) + 3
        bottom = int((target.y1 - clip.y0) * scale) + 3
        ImageDraw.Draw(image).rectangle((left, top, right, bottom), outline="red", width=2)
    return _png_data_url(image)


def _unicode_notation(text: str) -> list[str]:
    return [f"U+{ord(char):04X}" for char in text]


def _mask_unknown(text: str) -> str:
    masked = text.replace("\ufffd", "[UNKNOWN]").strip()
    return masked if "[UNKNOWN]" in masked else masked + " [UNKNOWN]"


def _position_label(page: fitz.Page, origin_y: float, target_size: float) -> str:
    nearby_origins: list[float] = []
    nearby_sizes: list[float] = []
    for span in page.get_texttrace():
        for _unicode, _gid, origin, _bbox in span.get("chars", ()):
            if abs(origin[1] - origin_y) <= max(8.0, target_size):
                nearby_origins.append(float(origin[1]))
                nearby_sizes.append(float(span.get("size", target_size)))
    if not nearby_origins:
        return "baseline"
    baseline = median(nearby_origins)
    normal_size = median(nearby_sizes)
    if target_size < normal_size * 0.9 and origin_y < baseline - 1.0:
        return "superscript"
    if target_size < normal_size * 0.9 and origin_y > baseline + 1.0:
        return "subscript"
    return "baseline"


def _page_glyph_matches(
    page: fitz.Page, base_font: str, gid: Optional[int]
) -> list[tuple[dict, tuple[float, float], fitz.Rect]]:
    matches = []
    for span in page.get_texttrace():
        if span.get("font") != base_font:
            continue
        for _unicode, char_gid, origin, bbox in span.get("chars", ()):
            if gid is not None and char_gid != gid:
                continue
            matches.append((span, origin, fitz.Rect(bbox)))
    return matches


def build_ambiguity_context(
    pdf_path: Path,
    finding: MissingUnicodeFinding,
    evidence: FontEvidence,
    *,
    max_occurrences: int = 3,
) -> dict:
    """Build visual, textual, and typographic evidence for the LLM fallback."""
    document = fitz.open(pdf_path)
    occurrences: list[dict] = []
    images: list[str] = []
    isolated: Optional[str] = None
    base_font = finding.base_font.lstrip("/")
    seen_pages: set[int] = set()
    try:
        page_numbers = list(dict.fromkeys(item.page_number for item in finding.occurrences))
        matches_by_page: dict[int, list[tuple[dict, tuple[float, float], fitz.Rect]]] = {}
        selected: list[tuple[int, dict, tuple[float, float], fitz.Rect]] = []
        for page_number in page_numbers:
            page = document[page_number - 1]
            matches = _page_glyph_matches(page, base_font, finding.gid)
            matches_by_page[page_number] = matches
            if matches and len(selected) < max_occurrences:
                selected.append((page_number, *matches[0]))
        if len(selected) < max_occurrences:
            for page_number in page_numbers:
                for match in matches_by_page.get(page_number, [])[1:]:
                    if len(selected) >= max_occurrences:
                        break
                    selected.append((page_number, *match))
                if len(selected) >= max_occurrences:
                    break

        for page_number, span, origin, bbox in selected:
            page = document[page_number - 1]
            line_clip = fitz.Rect(
                max(0, bbox.x0 - 130),
                max(0, bbox.y0 - 14),
                min(page.rect.width, bbox.x1 + 130),
                min(page.rect.height, bbox.y1 + 14),
            )
            paragraph_clip = fitz.Rect(
                0,
                max(0, bbox.y0 - 35),
                page.rect.width,
                min(page.rect.height, bbox.y1 + 35),
            )
            line_text = page.get_text("text", clip=line_clip)
            paragraph = page.get_text("text", clip=paragraph_clip).strip()
            occurrences.append(
                {
                    "page": page_number,
                    "masked_line": _mask_unknown(line_text),
                    "paragraph": _mask_unknown(paragraph),
                    "position": _position_label(page, float(origin[1]), float(span["size"])),
                    "font_size": round(float(span["size"]), 3),
                    "baseline_y": round(float(origin[1]), 3),
                }
            )
            images.append(_render_crop(page, line_clip, dpi=300, target=bbox))
            if isolated is None:
                isolated = _render_crop(
                    page,
                    fitz.Rect(bbox.x0 - 2, bbox.y0 - 2, bbox.x1 + 2, bbox.y1 + 2),
                    dpi=600,
                )
            seen_pages.add(page_number)
    finally:
        metadata = document.metadata or {}
        document.close()

    candidate_texts: set[str] = set()
    if finding.gid is not None:
        candidate_texts.update(evidence.unicode_by_gid.get(finding.gid, ()))
        glyph_name = evidence.glyph_name_by_gid.get(finding.gid)
        if glyph_name and evidence.unicode_by_glyph_name.get(glyph_name):
            candidate_texts.add(evidence.unicode_by_glyph_name[glyph_name])
    candidate_sequences = [
        notation
        for text in sorted(candidate_texts)
        for notation in _unicode_notation(text)
    ]
    contradictions = sorted(candidate_texts) if len(candidate_texts) > 1 else []
    if isolated:
        images.insert(0, isolated)
    return {
        "document_title": metadata.get("title") or pdf_path.stem,
        "font": finding.base_font,
        "cid": finding.cid,
        "gid": finding.gid,
        "glyph_name": evidence.glyph_name_by_gid.get(
            finding.gid if finding.gid is not None else -1
        ),
        "candidates": candidate_sequences,
        "deterministic_contradictions": contradictions,
        "occurrences": occurrences,
        "images": images,
        "sampled_pages": sorted(seen_pages),
    }


def _decode_utf16be(value: bytes) -> str:
    if len(value) % 2:
        raise ValueError("ToUnicode destination has an odd byte length")
    return value.decode("utf-16-be", errors="strict")


def parse_to_unicode_cmap(data: bytes) -> ParsedToUnicode:
    """Parse code-space width and bfchar/bfrange mappings from a CMap."""
    code_width = 2
    code_match = _CODESPACE_RE.search(data)
    if code_match:
        pair = _PAIR_RE.search(code_match.group(1))
        if pair:
            code_width = len(bytes.fromhex(pair.group(1).decode("ascii")))

    mappings: dict[int, str] = {}
    for block in _BFCHAR_RE.findall(data):
        for source, destination in _PAIR_RE.findall(block):
            mappings[int(source, 16)] = _decode_utf16be(bytes.fromhex(destination.decode("ascii")))

    for block in _BFRANGE_RE.findall(data):
        for line in block.splitlines():
            line = line.strip()
            if not line:
                continue
            scalar = re.match(
                rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>",
                line,
            )
            if scalar:
                start, end, destination = (int(value, 16) for value in scalar.groups())
                for offset, source in enumerate(range(start, end + 1)):
                    encoded = (destination + offset).to_bytes(
                        max(2, (destination.bit_length() + 7) // 8), "big"
                    )
                    if len(encoded) % 2:
                        encoded = b"\x00" + encoded
                    mappings[source] = _decode_utf16be(encoded)
                continue

            array_match = re.match(
                rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*\[(.*)\]",
                line,
            )
            if array_match:
                start, end = int(array_match.group(1), 16), int(array_match.group(2), 16)
                destinations = re.findall(rb"<([0-9A-Fa-f]+)>", array_match.group(3))
                if len(destinations) != end - start + 1:
                    raise ValueError("ToUnicode bfrange array length does not match source range")
                for source, destination in zip(range(start, end + 1), destinations):
                    mappings[source] = _decode_utf16be(
                        bytes.fromhex(destination.decode("ascii"))
                    )
    return ParsedToUnicode(code_width=code_width, mappings=mappings)


def add_cmap_mappings(data: bytes, mappings: dict[int, str]) -> bytes:
    """Return a CMap with new bfchar entries, preserving all existing entries."""
    parsed = parse_to_unicode_cmap(data)
    additions = {source: text for source, text in mappings.items() if source not in parsed.mappings}
    if not additions:
        return data
    marker = re.search(rb"\bendcmap\b", data)
    if not marker:
        raise ValueError("ToUnicode CMap has no endcmap marker")

    width = parsed.code_width * 2
    blocks: list[bytes] = []
    ordered = sorted(additions.items())
    for offset in range(0, len(ordered), 100):
        chunk = ordered[offset : offset + 100]
        lines = [f"{len(chunk)} beginbfchar".encode("ascii")]
        for source, text in chunk:
            destination = text.encode("utf-16-be").hex().upper()
            lines.append(f"<{source:0{width}X}> <{destination}>".encode("ascii"))
        lines.append(b"endbfchar")
        blocks.append(b"\n".join(lines))
    insertion = b"\n" + b"\n".join(blocks) + b"\n"
    return data[: marker.start()] + insertion + data[marker.start() :]


def _font_gid(font: pikepdf.Object, cid: int) -> Optional[int]:
    descendants = font.get("/DescendantFonts", [])
    if not descendants:
        return None
    mapping = descendants[0].get("/CIDToGIDMap")
    if mapping is None or str(mapping) == "/Identity":
        return cid
    if isinstance(mapping, pikepdf.Stream):
        raw = mapping.read_bytes()
        offset = cid * 2
        if offset + 2 <= len(raw):
            return int.from_bytes(raw[offset : offset + 2], "big")
    return None


def _string_bytes(operands: pikepdf.Array, operator: str) -> Iterable[bytes]:
    if operator == "TJ" and operands:
        for item in operands[0]:
            if isinstance(item, pikepdf.String):
                yield bytes(item)
        return
    for item in reversed(operands):
        if isinstance(item, pikepdf.String):
            yield bytes(item)
            return


def _iter_resource_streams(container: pikepdf.Object):
    yield container, container.get("/Resources", pikepdf.Dictionary())
    resources = container.get("/Resources", pikepdf.Dictionary())
    for _name, xobject in resources.get("/XObject", pikepdf.Dictionary()).items():
        if isinstance(xobject, pikepdf.Stream) and str(xobject.get("/Subtype", "")) == "/Form":
            yield from _iter_resource_streams(xobject)


def inventory_missing_unicode(pdf_path: Path) -> list[MissingUnicodeFinding]:
    """Find every used font character code absent from its ToUnicode CMap."""
    grouped: dict[tuple[tuple[int, int], int], tuple[pikepdf.Object, list[TextOccurrence]]] = {}
    with pikepdf.open(pdf_path) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            for stream_owner, resources in _iter_resource_streams(page.obj):
                fonts = resources.get("/Font", pikepdf.Dictionary())
                active_name: Optional[str] = None
                try:
                    instructions = pikepdf.parse_content_stream(stream_owner)
                except Exception:
                    continue
                for operands, operator in instructions:
                    name = str(operator)
                    if name == "Tf" and operands:
                        active_name = str(operands[0])
                        continue
                    if name not in {"Tj", "TJ", "'", '"'} or not active_name:
                        continue
                    font = fonts.get(active_name)
                    if font is None:
                        continue
                    cmap_stream = font.get("/ToUnicode")
                    if isinstance(cmap_stream, pikepdf.Stream):
                        parsed = parse_to_unicode_cmap(cmap_stream.read_bytes())
                    else:
                        parsed = ParsedToUnicode(code_width=2, mappings={})
                    width = parsed.code_width
                    for raw in _string_bytes(operands, name):
                        if len(raw) % width:
                            continue
                        for index in range(0, len(raw), width):
                            cid = int.from_bytes(raw[index : index + width], "big")
                            if cid in parsed.mappings:
                                continue
                            objgen = tuple(font.objgen)
                            occurrence = TextOccurrence(
                                page_number=page_number,
                                font_objgen=objgen,
                                resource_name=active_name,
                                cid=cid,
                            )
                            key = (objgen, cid)
                            if key not in grouped:
                                grouped[key] = (font, [])
                            grouped[key][1].append(occurrence)

        findings = []
        for (_objgen, cid), (font, occurrences) in grouped.items():
            findings.append(
                MissingUnicodeFinding(
                    font_objgen=tuple(font.objgen),
                    base_font=str(font.get("/BaseFont", "")),
                    cid=cid,
                    gid=_font_gid(font, cid),
                    occurrences=tuple(occurrences),
                )
            )
    return sorted(findings, key=lambda item: (item.font_objgen, item.cid))


def _write_unicode_mappings(
    source: Path,
    destination: Path,
    mappings: list[tuple[tuple[int, int], int, str]],
) -> None:
    by_font: dict[tuple[int, int], dict[int, str]] = {}
    for objgen, cid, text in mappings:
        by_font.setdefault(objgen, {})[cid] = text
    with pikepdf.open(source) as pdf:
        for objgen, additions in by_font.items():
            font = pdf.get_object(objgen)
            cmap = font.get("/ToUnicode")
            if not isinstance(cmap, pikepdf.Stream):
                raise ValueError(f"font {objgen} has no writable ToUnicode stream")
            cmap.write(add_cmap_mappings(cmap.read_bytes(), additions))
        pdf.save(destination)


def verify_repair(
    original: Path,
    candidate: Path,
    expected: list[tuple[tuple[int, int], int, str]],
    affected_pages: set[int],
) -> tuple[bool, str]:
    """Verify mappings are complete and page pixels are unchanged."""
    remaining = {
        (finding.font_objgen, finding.cid)
        for finding in inventory_missing_unicode(candidate)
    }
    for objgen, cid, _text in expected:
        if (objgen, cid) in remaining:
            return False, "mapping-still-missing"
    try:
        before = fitz.open(original)
        after = fitz.open(candidate)
        try:
            for page_number in sorted(affected_pages):
                before_pix = before[page_number - 1].get_pixmap(dpi=96, alpha=False)
                after_pix = after[page_number - 1].get_pixmap(dpi=96, alpha=False)
                if (
                    before_pix.width != after_pix.width
                    or before_pix.height != after_pix.height
                    or before_pix.samples != after_pix.samples
                ):
                    return False, f"visual-diff-page-{page_number}"
        finally:
            before.close()
            after.close()
    except Exception as exc:
        return False, f"render-verification-error: {exc}"
    return True, "ok"


def _disclosure(evaluated: int, applied: int, unavailable: bool) -> str:
    if unavailable:
        return (
            "DeepSeek V4 Pro was requested but unavailable; "
            "no ambiguous mappings were changed."
        )
    if evaluated == 0:
        return "DeepSeek V4 Pro was not used; all Unicode decisions were deterministic."
    return (
        f"DeepSeek V4 Pro evaluated {evaluated} ambiguous Unicode mapping(s); "
        f"{applied} recommendation(s) were applied."
    )


def repair_missing_unicode(
    pdf_path: Path,
    *,
    verifier=None,
    max_occurrences: int = 3,
) -> dict:
    """Resolve missing mappings and atomically install only verified changes."""
    findings = inventory_missing_unicode(pdf_path)
    accepted: list[tuple[tuple[int, int], int, str]] = []
    decisions: list[dict] = []
    evaluated = 0
    llm_applied = 0
    unavailable = False
    affected_pages: set[int] = set()

    for finding in findings:
        evidence = collect_font_evidence(pdf_path, finding)
        deterministic = resolve_deterministically(finding, evidence)
        if deterministic is not None:
            accepted.append((finding.font_objgen, finding.cid, deterministic.text))
            affected_pages.update(finding.pages)
            decisions.append(
                {
                    "font_objgen": list(finding.font_objgen),
                    "font": finding.base_font,
                    "cid": finding.cid,
                    "pages": list(finding.pages),
                    "occurrence_count": finding.occurrence_count,
                    "resolution_source": "font-metadata",
                    "llm_invoked": False,
                    "llm_recommendation_applied": False,
                    "unicode_text": deterministic.text,
                    "evidence": list(deterministic.evidence),
                }
            )
            continue

        if verifier is None:
            unavailable = True
            decisions.append(
                {
                    "font_objgen": list(finding.font_objgen),
                    "font": finding.base_font,
                    "cid": finding.cid,
                    "pages": list(finding.pages),
                    "occurrence_count": finding.occurrence_count,
                    "resolution_source": "unresolved",
                    "llm_invoked": False,
                    "llm_recommendation_applied": False,
                    "unresolved_reason": "deepseek-unavailable",
                }
            )
            continue

        context = build_ambiguity_context(
            pdf_path, finding, evidence, max_occurrences=max_occurrences
        )
        evaluated += 1
        decision = verifier(context)
        record = {
            "font_objgen": list(finding.font_objgen),
            "font": finding.base_font,
            "cid": finding.cid,
            "pages": list(finding.pages),
            "occurrence_count": finding.occurrence_count,
            "resolution_source": "deepseek-v4-pro",
            "llm_invoked": True,
            "llm_recommendation_applied": bool(decision.accepted),
            "confidence": decision.confidence,
        }
        if decision.accepted and decision.text:
            accepted.append((finding.font_objgen, finding.cid, decision.text))
            affected_pages.update(finding.pages)
            llm_applied += 1
            record["unicode_text"] = decision.text
        else:
            record["unresolved_reason"] = decision.rejection_reason or "rejected"
        decisions.append(record)

    details = {
        "llm_invoked": evaluated > 0,
        "llm_recommendation_applied": llm_applied > 0,
        "llm_unavailable": unavailable,
        "model": "deepseek-v4-pro" if evaluated else None,
        "evaluated": evaluated,
        "applied": llm_applied,
        "decisions": decisions,
    }
    disclosure = _disclosure(evaluated, llm_applied, unavailable)
    if not accepted:
        return {
            "issue_id": "pdf-unicode-mapping",
            "success": True,
            "message": disclosure,
            "new_value": "0 Unicode mapping(s) added",
            "details": details,
        }

    handle = tempfile.NamedTemporaryFile(
        prefix=f".{pdf_path.stem}.unicode-", suffix=".pdf", dir=pdf_path.parent, delete=False
    )
    candidate = Path(handle.name)
    handle.close()
    try:
        _write_unicode_mappings(pdf_path, candidate, accepted)
        verified, reason = verify_repair(pdf_path, candidate, accepted, affected_pages)
        if not verified:
            rollback_disclosure = _disclosure(evaluated, 0, unavailable)
            details["llm_recommendation_applied"] = False
            details["applied"] = 0
            for record in decisions:
                if record.get("llm_recommendation_applied"):
                    record["llm_recommendation_applied"] = False
                    record["unresolved_reason"] = f"rolled-back-{reason}"
            details["rollback_reason"] = reason
            return {
                "issue_id": "pdf-unicode-mapping",
                "success": False,
                "message": f"Unicode repair rolled back: {reason}. {rollback_disclosure}",
                "new_value": "0 Unicode mapping(s) added",
                "details": details,
            }
        os.replace(candidate, pdf_path)
        details["mappings_added"] = len(accepted)
        return {
            "issue_id": "pdf-unicode-mapping",
            "success": True,
            "message": disclosure,
            "new_value": f"{len(accepted)} Unicode mapping(s) added",
            "details": details,
        }
    finally:
        if candidate.exists():
            candidate.unlink()
