"""Rebuild existing TrueType CIDSet streams from complete embedded font evidence."""
from io import BytesIO
from pathlib import Path

from fontTools.ttLib import TTFont
import pikepdf


def _font_cids(font):
    if str(font.get("/Subtype", "")) != "/CIDFontType2":
        raise ValueError("CID font program type is not supported")
    descriptor = font.FontDescriptor
    program = descriptor.get("/FontFile2")
    if not isinstance(program, pikepdf.Stream):
        raise ValueError("No embedded TrueType program")
    with TTFont(BytesIO(program.read_bytes())) as embedded:
        count = int(embedded["maxp"].numGlyphs)
    if not 0 < count <= 65536:
        raise ValueError("Invalid embedded glyph count")
    mapping = font.get("/CIDToGIDMap", pikepdf.Name.Identity)
    if str(mapping) == "/Identity":
        return set(range(count))
    if not isinstance(mapping, pikepdf.Stream):
        raise ValueError("Unsupported CIDToGIDMap")
    raw = mapping.read_bytes()
    if not raw or len(raw) % 2 or len(raw) > 131072:
        raise ValueError("Invalid CIDToGIDMap length")
    gids = [int.from_bytes(raw[index:index + 2], "big") for index in range(0, len(raw), 2)]
    if any(gid >= count for gid in gids):
        raise ValueError("CIDToGIDMap refers to a glyph absent from the embedded font")
    # Entries mapping to glyph zero still identify a present .notdef glyph.
    return set(range(len(gids)))


def _bitset(cids):
    if not cids:
        raise ValueError("No authoritative CID membership")
    result = bytearray(max(cids) // 8 + 1)
    for cid in cids:
        result[cid // 8] |= 1 << (7 - cid % 8)
    return bytes(result)


def repair_cidsets(pdf_path: Path):
    repaired = 0
    unresolved = []
    with pikepdf.open(pdf_path, allow_overwriting_input=True) as pdf:
        descriptors = {}
        fonts = []
        for owner in pdf.objects:
            if isinstance(owner, pikepdf.Dictionary):
                if "/FontDescriptor" in owner:
                    fonts.append(owner)
                fonts.extend(owner.get("/DescendantFonts", []))
        for font in fonts:
            if not isinstance(font, pikepdf.Dictionary):
                continue
            descriptor = font.get("/FontDescriptor")
            if not isinstance(descriptor, pikepdf.Dictionary) or "/CIDSet" not in descriptor:
                continue
            key = descriptor.objgen if descriptor.objgen != (0, 0) else ("direct", id(descriptor))
            try:
                cids = _font_cids(font)
                if key in descriptors and descriptors[key][1] != cids:
                    raise ValueError("Shared descriptor has conflicting CID memberships")
                descriptors[key] = (descriptor, cids)
            except Exception as error:
                descriptors[key] = (descriptor, None)
                unresolved.append({"font": list(font.objgen), "reason": str(error)})
        for descriptor, cids in descriptors.values():
            if cids is None:
                continue
            stream = descriptor.get("/CIDSet")
            if not isinstance(stream, pikepdf.Stream):
                unresolved.append({"descriptor": list(descriptor.objgen), "reason": "CIDSet is not a stream"})
                continue
            expected = _bitset(cids)
            if stream.read_bytes() != expected:
                stream.write(expected)
                repaired += 1
        if repaired:
            pdf.save(pdf_path)
    return {"issue_id": "pdf-cidset", "success": not unresolved,
            "message": f"Rebuilt {repaired} CIDSet stream(s); {len(unresolved)} require font evidence",
            "new_value": f"{repaired} CIDSet streams", "details": {"unresolved": unresolved}}
