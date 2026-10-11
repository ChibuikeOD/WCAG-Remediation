from types import SimpleNamespace

import pytest

from backend.pdf_inline_scripts import associate_script_blocks, detect_script_runs
from backend.pdf_inline_scripts import inline_order_hints


def trace(text, x, y, size=12, direction=(1, 0)):
    chars = []
    for char in text:
        chars.append((ord(char), 0, (x, y), (x, y - size * .8, x + size * .5, y + size * .2)))
        x += size * .5
    return {"chars": chars, "size": size, "dir": direction}


class Page:
    def __init__(self, *spans):
        self.spans = spans

    def get_texttrace(self):
        raise AssertionError("unsafe text trace API must not be used")

    def get_text(self, format, flags=None):
        assert format == "rawdict"
        return {"blocks": [{"type": 0, "lines": [
            {"dir": span["dir"], "spans": [{"size": span["size"], "chars": [
                {"c": chr(code), "origin": origin, "bbox": bbox}
                for code, _gid, origin, bbox in span["chars"]]}]}
            for span in self.spans]}]}


@pytest.mark.parametrize("script,y,size,kind", [
    ("2", 96, 8, "superscript"), ("i", 103, 8, "subscript"),
    ("12", 96, 8, "superscript"), ("*", 96, 12, "superscript"),
    ("-12", 96, 8, "superscript"), ("²", 100, 12, "superscript"),
    ("ᵢ", 100, 12, "subscript"),
])
def test_separate_text_objects_keep_exact_script_and_base(script, y, size, kind):
    runs = detect_script_runs(Page(trace("x", 10, 100), trace(script, 16, y, size)))
    assert [(r.base_text, r.text, r.kind) for r in runs] == [("x", script, kind)]


def test_subscript_superscript_share_base():
    runs = detect_script_runs(Page(trace("x", 10, 100), trace("i", 16, 103, 8), trace("2", 20, 96, 8)))
    assert [(r.base_text, r.text, r.kind) for r in runs] == [
        ("x", "i", "subscript"), ("x", "2", "superscript")]


def test_script_drawing_before_its_base_and_split_digits():
    runs = detect_script_runs(Page(trace("2", 20, 96, 8), trace("1", 16, 96, 8), trace("x", 10, 100)))
    assert [(r.base_text, r.text, r.kind) for r in runs] == [("x", "12", "superscript")]


def test_chemistry_units_and_punctuation_are_not_swallowed():
    page = Page(trace("H", 10, 100), trace("2", 16, 103, 8), trace("O.", 20, 100))
    assert [(r.base_text, r.text) for r in detect_script_runs(page)] == [("H", "2")]


@pytest.mark.parametrize("span", [
    trace("12", 16, 118, 8),  # next line / note body
    trace("12", 200, 96, 8),  # page number / distant marker
    trace("A", 16, 100, 8),  # small caps / mixed font sizes
    trace("A", 16, 96, 20),  # heading
    trace("2", 16, 96, 8, (0, 1)),  # rotated text
])
def test_reject_unrelated_geometry(span):
    assert detect_script_runs(Page(trace("x", 10, 100), span)) == []


def block(text, bbox, tag="P", **metadata):
    return SimpleNamespace(text=text, tag=tag, metadata={"raw_bbox": bbox, **metadata})


def test_inline_parent_membership_without_semantic_guess():
    base = block("x", [10, 97, 16, 111], "Formula")
    script = block("12", [16, 102, 24, 111])
    repeated_note = block("12", [100, 10, 110, 20], "Note")
    layout = SimpleNamespace(height=200, blocks=[base, script, repeated_note])
    assert associate_script_blocks(Page(trace("x", 10, 100), trace("12", 16, 96, 8)), layout) == 1
    assert layout.blocks == [base, repeated_note]
    assert base.tag == "Formula"
    assert base.metadata["inline_scripts"][0]["text"] == "12"
    assert base.metadata["raw_bbox"] == [10, 97, 24, 111]


def test_preserve_explicit_reference_semantics():
    base = block("prose", [10, 97, 16, 111])
    reference = block("1", [16, 102, 20, 111], "Reference")
    layout = SimpleNamespace(height=200, blocks=[base, reference])
    assert associate_script_blocks(Page(trace("x", 10, 100), trace("1", 16, 96, 8)), layout) == 0
    assert layout.blocks == [base, reference]


def test_real_pdf_geometry_does_not_change_text_or_pixels():
    fitz = pytest.importorskip("fitz")
    document = fitz.open()
    page = document.new_page()
    page.insert_text((30, 100), "x", fontsize=12)
    page.insert_text((36, 96), "-12", fontsize=8)
    before_text = page.get_text()
    before_pixels = page.get_pixmap().samples
    assert [(r.base_text, r.text) for r in detect_script_runs(page)] == [("x", "-12")]
    assert page.get_text() == before_text
    assert page.get_pixmap().samples == before_pixels
    document.close()


def test_stacked_sub_superscript_order_remains_for_human_review():
    runs = [
        {"kind": "subscript", "bbox": [16, 100, 20, 108], "base_origin": [10, 100]},
        {"kind": "superscript", "bbox": [16.2, 89, 20.2, 98], "base_origin": [10, 100]},
    ]
    assert inline_order_hints(runs, 200) == ("", 1)

def test_raw_glyph_origins_preserve_inline_scripts_across_many_pages(tmp_path, monkeypatch):
    import fitz
    path = tmp_path / 'multipage.pdf'
    with fitz.open() as document:
        for _ in range(209):
            page = document.new_page()
            page.insert_text((30, 100), 'x', fontsize=12)
            page.insert_text((36, 96), '-12', fontsize=8)
            page.insert_text((30, 140), 'H', fontsize=12)
            page.insert_text((38, 143), '2', fontsize=8)
            page.insert_text((43, 140), 'O', fontsize=12)
        document.save(path)
    def forbidden(*args, **kwargs):
        raise AssertionError('native trace device is unsafe for the corpus lifecycle')
    monkeypatch.setattr(fitz.Page, 'get_texttrace', forbidden)
    with fitz.open(path) as document:
        for page in document:
            before_text = page.get_text()
            runs = detect_script_runs(page)
            assert [(r.base_text, r.text, r.kind) for r in runs] == [
                ('x', '-12', 'superscript'), ('H', '2', 'subscript')]
            assert page.get_text() == before_text
