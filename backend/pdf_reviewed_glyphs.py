"""Opt-in, byte-bound visual-review proposals; not authoritative font metadata."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pikepdf


def _sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fingerprint(font) -> str:
    digest = hashlib.sha256()
    for name, stream in sorted(font.CharProcs.items()):
        data = stream.read_bytes()
        digest.update(name.encode("ascii") + b"\0" + len(data).to_bytes(8, "big") + data)
    return digest.hexdigest()


def _glyph(font, code: int) -> str | None:
    encoding = font.get("/Encoding")
    if not isinstance(encoding, pikepdf.Dictionary):
        return None
    current = None
    for entry in encoding.get("/Differences", []):
        if isinstance(entry, int):
            current = entry
        elif current is not None:
            if current == code:
                return str(entry)
            current += 1
    return None


def _fonts(pdf, resource: str):
    seen = set()
    def visit(resources):
        font = resources.get("/Font", {}).get(resource)
        if font is not None and font.objgen not in seen:
            seen.add(font.objgen)
            yield font
        for _name, xobject in resources.get("/XObject", {}).items():
            if str(xobject.get("/Subtype")) == "/Form":
                key = ("form", xobject.objgen)
                if key not in seen:
                    seen.add(key)
                    yield from visit(xobject.get("/Resources", {}))
    for page in pdf.pages:
        yield from visit(page.get("/Resources", {}))


def _matches(font, binding, source):
    code = binding["character_code"]
    if isinstance(code, bool) or not isinstance(code, int) or not 0 <= code <= 255:
        return False
    if str(font.get("/Subtype")) != "/Type3":
        return False
    if _glyph(font, code) != binding["glyph_name"]:
        return False
    glyph = font.get("/CharProcs", {}).get(binding["glyph_name"])
    return (
        isinstance(glyph, pikepdf.Stream)
        and hashlib.sha256(glyph.read_bytes()).hexdigest() == binding["decoded_charproc_sha256"]
        and _fingerprint(font) == binding["font_fingerprint_sha256"]
        and hashlib.sha256(font.Encoding.unparse()).hexdigest() == source["verified_encoding_sha256"]
        and [float(x) for x in font.get("/FontMatrix", [])] == source["font_matrix"]
        and [float(x) for x in font.get("/FontBBox", [])] == source["font_bbox"]
    )


def load_reviewed_glyphs(sidecar: Path, original: Path, working_pdf: Path) -> dict:
    """Verify original bytes and bind proposals to unchanged working-font evidence.

    This does not trust a caller-supplied document hash, numeric glyph names,
    sidecar input paths or current object numbers after PDF rewrites. Invalid or
    conflicting proposals raise before any PDF mutation.
    """
    data = json.loads(sidecar.read_text(encoding="utf-8-sig"))
    if data.get("schema_version") != "pdfaccess.glyph-proposals.v1" or data.get("review_status") != "REVIEWED":
        raise ValueError("unreviewed or unsupported glyph sidecar")
    original_sha = _sha_file(original)
    sources = {s["source_id"]: s for s in data["sources"] if s["input_sha256"] == original_sha}
    if not sources:
        raise ValueError("glyph sidecar does not match original document SHA256")
    result = {}
    with pikepdf.open(original) as original_pdf, pikepdf.open(working_pdf) as target:
        original_resources_cache = {}
        target_fonts_cache = {}
        for proposal in data["proposals"]:
            if proposal.get("review_status") != "REVIEWED":
                continue
            text = proposal.get("proposed_unicode")
            if not isinstance(text, str) or not text or any(ord(c) < 32 or c == "\ufffd" or 0xD800 <= ord(c) <= 0xDFFF for c in text):
                raise ValueError("invalid reviewed Unicode text")
            for binding in proposal["bindings"]:
                source = sources.get(binding["source_id"])
                if source is None:
                    continue
                if binding["input_sha256"] != original_sha or binding["font_objgen"] != source["font_objgen"] or binding["font_resource"] != source["font_resource"]:
                    raise ValueError("inconsistent original font binding")
                original_font = original_pdf.get_object(tuple(binding["font_objgen"]))
                source = dict(source)
                encoding_sha = hashlib.sha256(original_font.Encoding.unparse()).hexdigest()
                if any(record.get("font_encoding_sha256", encoding_sha) != encoding_sha for record in (source, binding)):
                    raise ValueError("reviewed original encoding hash does not match")
                source["verified_encoding_sha256"] = encoding_sha
                resource = binding["font_resource"]
                if resource not in original_resources_cache:
                    original_resources_cache[resource] = {f.objgen for f in _fonts(original_pdf, resource)}
                    target_fonts_cache[resource] = list(_fonts(target, resource))
                original_resources = original_resources_cache[resource]
                if original_font.objgen not in original_resources or not _matches(original_font, binding, source):
                    raise ValueError("reviewed original font evidence does not match")
                for font in target_fonts_cache[resource]:
                    if not _matches(font, binding, source):
                        continue
                    key = (font.objgen, binding["character_code"])
                    cmap = font.get("/ToUnicode")
                    if isinstance(cmap, pikepdf.Stream):
                        from .pdf_unicode_mapping import parse_to_unicode_cmap
                        existing = parse_to_unicode_cmap(cmap.read_bytes()).mappings.get(key[1])
                        if existing is not None and existing != text:
                            raise ValueError("reviewed glyph conflicts with existing ToUnicode")
                    if key in result and result[key]["text"] != text:
                        raise ValueError("conflicting reviewed glyph mappings")
                    result[key] = {"text": text, "resolution_source": "model-reviewed-sidecar",
                                   "proposal_id": proposal["proposal_id"], "source_sha256": original_sha,
                                   "decoded_charproc_sha256": binding["decoded_charproc_sha256"],
                                   "font_metadata_authority": False}
    return result
