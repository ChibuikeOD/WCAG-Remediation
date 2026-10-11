"""Recover script Unicode only from an exactly verified local reference font."""
from __future__ import annotations
from pathlib import Path
import os
from fontTools.ttLib import TTCollection, TTFont


def _identity(font):
    if not all(tag in font for tag in ('name', 'head', 'maxp', 'GSUB', 'glyf', 'hmtx')):
        return None
    names = {}
    for record in font['name'].names:
        if record.nameID in {5, 6}:
            try:
                names.setdefault(record.nameID, set()).add(record.toUnicode())
            except UnicodeError:
                return None
    if set(names) != {5, 6}:
        return None
    return (names, font['head'].unitsPerEm, font['head'].fontRevision,
            font['maxp'].numGlyphs)


def verified_ssty_unicode(source: TTFont, reference: TTFont) -> dict[int, tuple[str, ...]]:
    """Match retained glyphs and complete shaping table; reject conflicting aliases.

    Only ssty (mathematical script styling) is eligible. The embedded base glyph
    may be pruned; the retained target outline and metrics must match exactly.
    No font program is replaced or written.
    """
    identity = _identity(source)
    if identity is None or identity != _identity(reference):
        return {}
    if source.getTableData('GSUB') != reference.getTableData('GSUB'):
        return {}
    source_order, reference_order = source.getGlyphOrder(), reference.getGlyphOrder()
    source_gid = {name: gid for gid, name in enumerate(source_order)}
    reference_gid = {name: gid for gid, name in enumerate(reference_order)}
    unicode_by_gid = {}
    if 'cmap' in reference:
        for table in reference['cmap'].tables:
            if table.isUnicode():
                for cp, name in table.cmap.items():
                    unicode_by_gid.setdefault(reference_gid[name], set()).add(chr(cp))
    gsub = source['GSUB'].table
    if gsub.FeatureList is None or gsub.LookupList is None:
        return {}
    candidates = {}
    for feature in gsub.FeatureList.FeatureRecord:
        if feature.FeatureTag != 'ssty':
            continue
        for index in feature.Feature.LookupListIndex:
            lookup = gsub.LookupList.Lookup[index]
            for subtable in lookup.SubTable:
                kind = lookup.LookupType
                if kind == 7:
                    kind, subtable = subtable.ExtensionLookupType, subtable.ExtSubTable
                if kind == 3:
                    mapping = subtable.alternates
                elif kind == 1:
                    mapping = {base: [target] for base, target in subtable.mapping.items()}
                else:
                    continue
                for base, targets in mapping.items():
                    base_gid = source_gid[base]
                    values = unicode_by_gid.get(base_gid, set())
                    for target in targets:
                        gid = source_gid[target]
                        candidates.setdefault(gid, set()).update(values)
    result = {}
    for gid, values in candidates.items():
        if len(values) != 1:
            continue
        left, right = source_order[gid], reference_order[gid]
        if source['hmtx'].metrics[left] != reference['hmtx'].metrics[right]:
            continue
        glyph = source['glyf'][left]
        if glyph.numberOfContours == 0:
            continue
        if glyph.compile(source['glyf']) != reference['glyf'][right].compile(reference['glyf']):
            continue
        # A direct cmap alias must agree with the styled base's canonical text.
        direct = unicode_by_gid.get(gid, set())
        if direct and direct != values:
            continue
        result[gid] = tuple(values)
    return result


def collect_verified_local_ssty(source: TTFont, paths=None):
    if paths is None:
        paths = [Path('C:/Windows/Fonts/cambria.ttc')] if os.name == 'nt' else []
    combined = {}
    for path in paths:
        path = Path(path)
        if not path.is_file():
            continue
        fonts = []
        collection = None
        try:
            if path.suffix.lower() == '.ttc':
                collection = TTCollection(path, lazy=False)
                fonts = collection.fonts
            else:
                fonts = [TTFont(path, lazy=False)]
            for reference in fonts:
                for gid, values in verified_ssty_unicode(source, reference).items():
                    combined.setdefault(gid, set()).update(values)
        except (OSError, ValueError, KeyError):
            continue
        finally:
            if collection is not None:
                collection.close()
            else:
                for font in fonts:
                    font.close()
    return {gid: tuple(values) for gid, values in combined.items() if len(values) == 1}
