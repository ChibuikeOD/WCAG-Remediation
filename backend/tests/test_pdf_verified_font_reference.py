from copy import deepcopy
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.feaLib.builder import addOpenTypeFeaturesFromString
from backend.pdf_verified_font_reference import verified_ssty_unicode, collect_verified_local_ssty


def font():
    fb = FontBuilder(1000, isTTF=True)
    fb.setupGlyphOrder(['.notdef', 'four', 'four.script'])
    glyphs = {}
    for name in ['.notdef', 'four', 'four.script']:
        pen = TTGlyphPen(None)
        if name != '.notdef':
            pen.moveTo((10, 0)); pen.lineTo((200, 400)); pen.lineTo((350, 0)); pen.closePath()
        glyphs[name] = pen.glyph()
    fb.setupGlyf(glyphs)
    fb.setupHorizontalMetrics({name: (400, 10) for name in glyphs})
    fb.setupHorizontalHeader(ascent=800, descent=-200)
    fb.setupCharacterMap({52: 'four'})
    fb.setupNameTable({'familyName': 'TestMath', 'styleName': 'Regular',
                      'psName': 'TestMath', 'version': 'Version 1.0'})
    fb.setupOS2(); fb.setupPost(); fb.setupMaxp()
    addOpenTypeFeaturesFromString(fb.font, 'feature ssty { sub four from [four.script]; } ssty;')
    return fb.font


def test_pruned_base_retained_script_matches_authoritative_reference():
    reference = font(); source = deepcopy(reference)
    for table in source['cmap'].tables:
        table.cmap = {}
    pen = TTGlyphPen(None)
    source['glyf']['four'] = pen.glyph()
    source['hmtx'].metrics['four'] = (0, 0)
    assert verified_ssty_unicode(source, reference) == {2: ('4',)}
    assert collect_verified_local_ssty(source, []) == {}


def test_mismatched_metrics_outline_identity_and_shaping_rejected():
    reference = font()
    source = deepcopy(reference); source['hmtx'].metrics['four.script'] = (401, 10)
    assert verified_ssty_unicode(source, reference) == {}
    source = deepcopy(reference); source['glyf']['four.script'].coordinates[0] = (11, 0)
    assert verified_ssty_unicode(source, reference) == {}
    source = deepcopy(reference); source['head'].unitsPerEm = 2048
    assert verified_ssty_unicode(source, reference) == {}
    source = deepcopy(reference); source['GSUB'].table.FeatureList.FeatureRecord[0].FeatureTag = 'subs'
    assert verified_ssty_unicode(source, reference) == {}


def test_conflicting_canonical_alias_and_target_alias_rejected():
    reference = font(); source = deepcopy(reference)
    for table in reference['cmap'].tables:
        table.cmap[0x34FF] = 'four'
    assert verified_ssty_unicode(source, reference) == {}
    reference = font()
    for table in reference['cmap'].tables:
        table.cmap[0x2074] = 'four.script'
    assert verified_ssty_unicode(source, reference) == {}
