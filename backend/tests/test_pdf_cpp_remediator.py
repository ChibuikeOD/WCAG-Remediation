import json
import shutil
import subprocess
from pathlib import Path

import pikepdf


REPO_ROOT = Path(__file__).resolve().parents[2]


def _cpp_binary() -> Path:
    candidates = [
        REPO_ROOT / "pdfua_remediator_cpp" / "build-pacfix" / "Release" / "pdfua-remediator-cli.exe",
        REPO_ROOT / "pdfua_remediator_cpp" / "build-pacfix" / "pdfua-remediator-cli",
        REPO_ROOT / "pdfua_remediator_cpp" / "build-pacfix" / "Release" / "pdfua-remediator-cli",
        REPO_ROOT / "pdfua_remediator_cpp" / "build" / "Release" / "pdfua-remediator-cli.exe",
        REPO_ROOT / "pdfua_remediator_cpp" / "build" / "pdfua-remediator-cli",
        REPO_ROOT / "pdfua_remediator_cpp" / "build" / "Release" / "pdfua-remediator-cli",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise AssertionError("C++ remediator binary is not built")


def _run_cpp_remediator(input_pdf: Path, layout_blocks: list[dict], output_pdf: Path) -> None:
    layout_path = output_pdf.with_suffix(".layout.json")
    layout_path.write_text(json.dumps(layout_blocks), encoding="utf-8")
    subprocess.run(
        [str(_cpp_binary()), str(input_pdf), str(layout_path), str(output_pdf)],
        check=True,
        capture_output=True,
        text=True,
    )


def _write_pdf_with_artifact_form_xobject(path: Path) -> None:
    with pikepdf.Pdf.new() as pdf:
        page = pdf.add_blank_page(page_size=(612, 792))
        form = pdf.make_stream(
            b"/Artifact <</Type /Page>> BDC 0 0 270 10 re f EMC"
        )
        form["/Type"] = pikepdf.Name("/XObject")
        form["/Subtype"] = pikepdf.Name("/Form")
        form["/BBox"] = pikepdf.Array([0, 0, 270, 10])
        page.obj["/Resources"] = pikepdf.Dictionary({
            "/XObject": pikepdf.Dictionary({"/X0": form}),
        })
        page.obj["/Contents"] = pdf.make_stream(b"q 1 0 0 1 15 772 cm /X0 Do Q")
        pdf.save(path)


def _write_pdf_with_table_text(path: Path) -> None:
    with pikepdf.Pdf.new() as pdf:
        page = pdf.add_blank_page(page_size=(612, 792))
        page.obj["/Resources"] = pikepdf.Dictionary({
            "/Font": pikepdf.Dictionary({
                "/F1": pikepdf.Dictionary({
                    "/Type": pikepdf.Name("/Font"),
                    "/Subtype": pikepdf.Name("/Type1"),
                    "/BaseFont": pikepdf.Name("/Helvetica"),
                })
            })
        })
        page.obj["/Contents"] = pdf.make_stream(
            b"BT /F1 12 Tf 50 720 Td (Question) Tj ET "
            b"BT /F1 12 Tf 250 720 Td (Percent) Tj ET "
            b"BT /F1 12 Tf 50 690 Td (Behavioral) Tj ET "
            b"BT /F1 12 Tf 250 690 Td (16.0) Tj ET"
        )
        pdf.save(path)


def _write_pdf_with_figure_form_xobject(path: Path) -> None:
    with pikepdf.Pdf.new() as pdf:
        page = pdf.add_blank_page(page_size=(612, 792))
        form = pdf.make_stream(b"0 0 120 40 re f")
        form["/Type"] = pikepdf.Name("/XObject")
        form["/Subtype"] = pikepdf.Name("/Form")
        form["/BBox"] = pikepdf.Array([0, 0, 120, 40])
        page.obj["/Resources"] = pikepdf.Dictionary({
            "/XObject": pikepdf.Dictionary({"/X1": form}),
        })
        page.obj["/Contents"] = pdf.make_stream(b"q 1 0 0 1 60 690 cm /X1 Do Q")
        pdf.save(path)


def _write_pdf_with_single_text_run(path: Path) -> None:
    with pikepdf.Pdf.new() as pdf:
        page = pdf.add_blank_page(page_size=(612, 792))
        page.obj["/Resources"] = pikepdf.Dictionary({
            "/Font": pikepdf.Dictionary({
                "/F1": pikepdf.Dictionary({
                    "/Type": pikepdf.Name("/Font"),
                    "/Subtype": pikepdf.Name("/Type1"),
                    "/BaseFont": pikepdf.Name("/Helvetica"),
                })
            })
        })
        page.obj["/Contents"] = pdf.make_stream(b"BT /F1 12 Tf 50 720 Td (Readable text) Tj ET")
        pdf.save(path)


def _walk_struct_elems(obj):
    if not hasattr(obj, "get"):
        return
    if obj.get("/Type") == "/StructElem":
        yield obj
    kids = obj.get("/K")
    if isinstance(kids, pikepdf.Array):
        for kid in kids:
            yield from _walk_struct_elems(kid)
    elif hasattr(kids, "get"):
        yield from _walk_struct_elems(kids)


def _struct_kids(kids):
    if kids is None:
        return []
    return list(kids) if isinstance(kids, pikepdf.Array) else [kids]


def _is_integer_obj(obj):
    return isinstance(obj, int) or (hasattr(obj, "is_integer") and obj.is_integer())


def test_artifact_form_xobjects_are_not_wrapped_as_tagged_figures(tmp_path):
    source = tmp_path / "artifact-form.pdf"
    output = tmp_path / "tagged.pdf"
    _write_pdf_with_artifact_form_xobject(source)

    _run_cpp_remediator(source, [], output)

    with pikepdf.open(output) as pdf:
        instructions = list(pikepdf.parse_content_stream(pdf.pages[0]))
        do_indexes = [i for i, ins in enumerate(instructions) if str(ins.operator) == "Do"]
        assert do_indexes
        for index in do_indexes:
            window = instructions[max(0, index - 4): index + 3]
            assert not any(
                str(ins.operator) == "BDC"
                and ins.operands
                and str(ins.operands[0]) == "/Figure"
                for ins in window
            )


def test_struct_tree_uses_explicit_mcr_dictionaries_for_screen_readers(tmp_path):
    source = tmp_path / "text.pdf"
    output = tmp_path / "tagged.pdf"
    _write_pdf_with_single_text_run(source)
    blocks = [
        {
            "page": 0,
            "tag": "P",
            "bbox": [45, 710, 220, 735],
        }
    ]

    _run_cpp_remediator(source, blocks, output)

    with pikepdf.open(output) as pdf:
        root_k = pdf.Root["/StructTreeRoot"]["/K"]
        roots = list(root_k) if isinstance(root_k, pikepdf.Array) else [root_k]
        struct_elems = [
            elem
            for root in roots
            for elem in _walk_struct_elems(root)
        ]
        content_refs = []
        for elem in struct_elems:
            for kid in _struct_kids(elem.get("/K")):
                assert not _is_integer_obj(kid)
                if hasattr(kid, "get") and kid.get("/Type") == "/MCR":
                    content_refs.append(kid)

        assert content_refs
        for ref in content_refs:
            assert ref.get("/Pg") is not None
            assert ref.get("/MCID") is not None


def test_empty_layout_blocks_are_not_emitted_as_empty_structure_elements(tmp_path):
    source = tmp_path / "text.pdf"
    output = tmp_path / "tagged.pdf"
    _write_pdf_with_single_text_run(source)
    blocks = [
        {
            "page": 0,
            "tag": "P",
            "bbox": [45, 710, 220, 735],
        },
        {
            "page": 0,
            "tag": "P",
            "bbox": [300, 100, 420, 130],
        },
    ]

    _run_cpp_remediator(source, blocks, output)

    with pikepdf.open(output) as pdf:
        root_k = pdf.Root["/StructTreeRoot"]["/K"]
        roots = list(root_k) if isinstance(root_k, pikepdf.Array) else [root_k]
        struct_elems = [
            elem
            for root in roots
            for elem in _walk_struct_elems(root)
        ]
        assert struct_elems
        empty_elems = [
            elem
            for elem in struct_elems
            if elem.get("/Type") == "/StructElem" and not _struct_kids(elem.get("/K"))
        ]
        assert empty_elems == []


def test_figure_mcids_do_not_keep_overlapping_text_blocks_alive(tmp_path):
    source = tmp_path / "figure-form.pdf"
    output = tmp_path / "tagged.pdf"
    _write_pdf_with_figure_form_xobject(source)
    blocks = [
        {
            "page": 0,
            "tag": "P",
            "bbox": [55, 685, 190, 740],
        },
    ]

    _run_cpp_remediator(source, blocks, output)

    with pikepdf.open(output) as pdf:
        root_k = pdf.Root["/StructTreeRoot"]["/K"]
        roots = list(root_k) if isinstance(root_k, pikepdf.Array) else [root_k]
        struct_elems = [
            elem
            for root in roots
            for elem in _walk_struct_elems(root)
        ]
        roles = [elem.get("/S") for elem in struct_elems]
        assert "/Figure" in roles
        empty_elems = [
            elem
            for elem in struct_elems
            if elem.get("/Type") == "/StructElem" and not _struct_kids(elem.get("/K"))
        ]
        assert empty_elems == []


def test_table_header_scope_is_written_as_table_attribute(tmp_path):
    source = tmp_path / "table.pdf"
    output = tmp_path / "tagged.pdf"
    _write_pdf_with_table_text(source)
    blocks = [
        {
            "page": 0,
            "tag": "TH",
            "bbox": [45, 710, 180, 735],
            "table_id": "t1",
            "table_row": 0,
            "table_col": 0,
            "table_header": True,
        },
        {
            "page": 0,
            "tag": "TH",
            "bbox": [245, 710, 330, 735],
            "table_id": "t1",
            "table_row": 0,
            "table_col": 1,
            "table_header": True,
        },
        {
            "page": 0,
            "tag": "TH",
            "bbox": [45, 680, 180, 705],
            "table_id": "t1",
            "table_row": 1,
            "table_col": 0,
            "table_header": True,
        },
        {
            "page": 0,
            "tag": "TD",
            "bbox": [245, 680, 330, 705],
            "table_id": "t1",
            "table_row": 1,
            "table_col": 1,
            "table_header": False,
        },
    ]

    _run_cpp_remediator(source, blocks, output)

    with pikepdf.open(output) as pdf:
        root_k = pdf.Root["/StructTreeRoot"]["/K"]
        roots = list(root_k) if isinstance(root_k, pikepdf.Array) else [root_k]
        th_elems = [
            elem
            for root in roots
            for elem in _walk_struct_elems(root)
            if elem.get("/S") == "/TH"
        ]
        assert th_elems
        for th in th_elems:
            assert th.get("/Scope") is None
            attrs = th.get("/A")
            attr_items = list(attrs) if isinstance(attrs, pikepdf.Array) else [attrs]
            assert any(
                hasattr(attr, "get")
                and attr.get("/O") == "/Table"
                and attr.get("/Scope") in ("/Row", "/Column")
                for attr in attr_items
            )
