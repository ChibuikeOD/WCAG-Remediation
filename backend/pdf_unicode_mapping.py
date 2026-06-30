"""Detect and repair incomplete PDF ToUnicode character maps."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Iterable, Optional

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
