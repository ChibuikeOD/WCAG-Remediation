"""Integration checks require a binary built from the tested native sources."""
import json
import os
from pathlib import Path
import subprocess

import pytest
import pikepdf


@pytest.fixture
def native_cli():
    configured = os.environ.get("PDFACCESS_TEST_NATIVE_CLI")
    default = Path(__file__).resolve().parents[2] / "pdfua_remediator_cpp/build/Release/pdfua-remediator-cli.exe"
    path = Path(configured) if configured else default
    if not path.is_file():
        pytest.skip("Build the current native sources or set PDFACCESS_TEST_NATIVE_CLI")
    return path


@pytest.mark.parametrize("drawing_order", [(0, 1, 2), (1, 0, 2), (0, 2, 1)])
def test_native_script_sequence_parent_and_pixels(native_cli, tmp_path, drawing_order):
    fitz = pytest.importorskip("fitz")
    from backend.pdf_inline_scripts import associate_script_blocks
    from types import SimpleNamespace

    original = tmp_path / "original.pdf"
    output = tmp_path / "tagged.pdf"
    mapping = tmp_path / "layout.json"
    document = fitz.open()
    page = document.new_page(width=200, height=200)
    fragments = [((30, 100), "x", 12), ((36, 96), "-12", 8), ((48, 100), "=y", 12)]
    for index in drawing_order:
        pos, text, size = fragments[index]
        page.insert_text(pos, text, fontsize=size)
    document.save(original)
    layout = SimpleNamespace(height=200, blocks=[
        SimpleNamespace(tag="Formula", text="x=y", metadata={"raw_bbox": [30, 97, 70, 111]}),
        SimpleNamespace(tag="P", text="-12", metadata={"raw_bbox": [36, 102, 48, 111]}),
    ])
    associate_script_blocks(page, layout)
    mapping_data = []
    for b in layout.blocks:
        data = {"page": 0, "tag": b.tag, "bbox": b.metadata["raw_bbox"]}
        hints = []
        for run in b.metadata.get("inline_scripts", []):
            x0, y0, x1, y1 = run["bbox"]
            bx, by = run["base_origin"]
            hints.append(",".join(str(v) for v in (x0, 200 - y1, x1, 200 - y0, bx, 200 - by)))
        if hints:
            data["inline_order"] = ";".join(hints)
        mapping_data.append(data)
    mapping.write_text(json.dumps(mapping_data), encoding="utf-8")
    before_text = page.get_text()
    before_pixels = page.get_pixmap().samples
    document.close()
    subprocess.run([str(native_cli), str(original), str(mapping), str(output)], check=True, capture_output=True, timeout=30)
    with fitz.open(output) as tagged:
        assert tagged[0].get_text() == before_text
        assert tagged[0].get_pixmap().samples == before_pixels
    with pikepdf.open(output) as pdf:
        parents = pdf.Root.StructTreeRoot.K[0].K
        assert len(parents) == 1
        assert str(parents[0].S) == "/Formula"
        mcid_text = {}
        current = None
        for operands, operator in pikepdf.parse_content_stream(pdf.pages[0]):
            op = str(operator)
            if op == "BDC":
                current = int(operands[1]["/MCID"])
            elif op == "EMC":
                current = None
            elif op == "Tj" and current is not None:
                mcid_text[current] = mcid_text.get(current, "") + bytes(operands[0]).decode("ascii")
            elif op == "TJ" and current is not None:
                text = "".join(bytes(part).decode("ascii") for part in operands[0] if isinstance(part, pikepdf.String))
                mcid_text[current] = mcid_text.get(current, "") + text
        assert "".join(mcid_text[int(k.MCID)] for k in parents[0].K) == "x-12=y"
        parent_tree = pdf.Root.StructTreeRoot.ParentTree.Nums[1]
        assert all(k == parents[0] for k in parent_tree)


def test_native_unique_notes(native_cli, tmp_path):
    source = tmp_path / "notes.pdf"
    output = tmp_path / "notes-tagged.pdf"
    layout = tmp_path / "notes.json"
    with pikepdf.Pdf.new() as pdf:
        font = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type1, BaseFont=pikepdf.Name.Helvetica))
        for _ in range(2):
            page = pdf.add_blank_page(page_size=(200, 200))
            page.Resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=font))
            page.Contents = pdf.make_stream(b"BT /F1 12 Tf 30 100 Td (1 Note body) Tj ET")
        pdf.save(source)
    layout.write_text(json.dumps([{"page": i, "tag": "Note", "bbox": [30, 95, 150, 115]} for i in range(2)]), encoding="utf-8")
    subprocess.run([str(native_cli), str(source), str(layout), str(output)], check=True, capture_output=True, timeout=30)
    with pikepdf.open(output) as pdf:
        notes = list(pdf.Root.StructTreeRoot.K[0].K)
        assert [str(note.S) for note in notes] == ["/Note", "/Note"]
        assert len({str(note.ID) for note in notes}) == 2
        names = pdf.Root.StructTreeRoot.IDTree.Names
        assert len(names) == 4
        assert names[1] == notes[0]
        assert names[3] == notes[1]


@pytest.mark.parametrize("description", [None, "Measured pressure rises as the chamber volume decreases."])
def test_native_figure_alt_is_supplied_or_unresolved(native_cli, tmp_path, description):
    source = tmp_path / "figure.pdf"
    output = tmp_path / "figure-tagged.pdf"
    mapping = tmp_path / "figure-layout.json"
    with pikepdf.Pdf.new() as pdf:
        page = pdf.add_blank_page(page_size=(100, 100))
        image = pdf.make_stream(bytes([100, 100, 100]))
        image.Type = pikepdf.Name.XObject
        image.Subtype = pikepdf.Name.Image
        image.Width = 1
        image.Height = 1
        image.ColorSpace = pikepdf.Name.DeviceRGB
        image.BitsPerComponent = 8
        page.Resources = pikepdf.Dictionary(XObject=pikepdf.Dictionary(Im=image))
        page.Contents = pdf.make_stream(b"q 20 0 0 20 30 30 cm /Im Do Q")
        pdf.save(source)
    data = {"page": 0, "tag": "Figure", "bbox": [30, 30, 50, 50]}
    if description:
        data["alt_hex"] = description.encode("utf-8").hex()
    mapping.write_text(json.dumps([data]), encoding="utf-8")
    subprocess.run([str(native_cli), str(source), str(mapping), str(output)], check=True, capture_output=True, timeout=30)
    with pikepdf.open(output) as pdf:
        figure = pdf.Root.StructTreeRoot.K[0].K[0]
        assert str(figure.S) == "/Figure"
        if description:
            assert str(figure.Alt) == description
        else:
            assert "/Alt" not in figure


def test_native_text_rise_groups_script_without_changing_fidelity(native_cli, tmp_path):
    fitz = pytest.importorskip("fitz")
    source, output, layout = (tmp_path / name for name in ("rise.pdf", "rise-tagged.pdf", "rise.json"))
    with pikepdf.Pdf.new() as pdf:
        page = pdf.add_blank_page(page_size=(200, 200))
        font = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type1, BaseFont=pikepdf.Name.Helvetica))
        page.Resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=font))
        page.Contents = pdf.make_stream(b"BT /F1 12 Tf 30 100 Td (x) Tj ET BT /F1 8 Tf 36 100 Td 4 Ts (-12) Tj ET")
        pdf.save(source)
    # Native position assignment must honor Ts: the script region is not at
    # the unshifted text matrix's y=100 origin.
    layout.write_text(json.dumps([
        {"page": 0, "tag": "P", "bbox": [30, 97, 36, 101]},
        {"page": 0, "tag": "Reference", "bbox": [36, 102, 48, 112],
         "inline_parent_id": "rise-parent"},
    ]), encoding="utf-8")
    subprocess.run([str(native_cli), str(source), str(layout), str(output)], check=True, capture_output=True, timeout=30)
    with fitz.open(source) as before, fitz.open(output) as after:
        assert before[0].get_text() == after[0].get_text()
        assert before[0].get_pixmap().samples == after[0].get_pixmap().samples
    with pikepdf.open(output) as pdf:
        parents = pdf.Root.StructTreeRoot.K[0].K
        reference = [p for p in parents if str(p.S) == "/Reference"][0]
        assert [int(k.MCID) for k in reference.K] == [1]


def test_native_explicit_reference_has_inline_parent_and_exact_order(native_cli, tmp_path):
    source, output, layout = (tmp_path / name for name in ("reference.pdf", "reference-tagged.pdf", "reference.json"))
    with pikepdf.Pdf.new() as pdf:
        page = pdf.add_blank_page(page_size=(200, 200))
        font = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type1, BaseFont=pikepdf.Name.Helvetica))
        page.Resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=font))
        # Marker drawn after the following punctuation.
        page.Contents = pdf.make_stream(b"BT /F1 12 Tf 30 100 Td (prose) Tj ET BT /F1 12 Tf 70 100 Td (.) Tj ET BT /F1 8 Tf 60 104 Td (12) Tj ET")
        pdf.save(source)
    layout.write_text(json.dumps([
        {"page": 0, "tag": "P", "bbox": [30, 97, 90, 113], "inline_group_id": "parent1",
         "inline_order": "60,102,69,112,30,100"},
        {"page": 0, "tag": "Reference", "bbox": [60, 102, 69, 112], "inline_parent_id": "parent1"},
    ]), encoding="utf-8")
    subprocess.run([str(native_cli), str(source), str(layout), str(output)], check=True, capture_output=True, timeout=30)
    with pikepdf.open(output) as pdf:
        parents = pdf.Root.StructTreeRoot.K[0].K
        assert len(parents) == 1 and str(parents[0].S) == "/P"
        body, reference, punctuation = parents[0].K
        assert int(body.MCID) == 0
        assert str(reference.S) == "/Reference" and reference.P == parents[0]
        assert int(reference.K[0].MCID) == 2
        assert int(punctuation.MCID) == 1
        assert "/Annots" not in pdf.pages[0].obj
