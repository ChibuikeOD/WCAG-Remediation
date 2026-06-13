"""
Tests for LayoutLM-backed PDF auto-tagging flow.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.layout_model import (
    DocumentLayoutAnalyzer,
    LABEL_TO_TAG,
    PageLayout,
    StructureBlock,
    ensure_hf_model_layout,
    resolve_layoutlm_model_dir,
)
from backend.pdf_auto_tagging import auto_tag_pdf
from backend.pdf_overlay_debug import build_block_label
from backend.pdf_structure_builder import TaggingResult

import pikepdf


FIXTURES_DIR = Path(__file__).parent / "fixtures"
REPO_ROOT = Path(__file__).parent.parent.parent


def make_minimal_pdf(path: Path, language: str = "en") -> None:
    with pikepdf.Pdf.new() as pdf:
        pdf.add_blank_page(page_size=(72, 72))
        pdf.Root.Lang = pikepdf.String(language)
        pdf.save(path)


def test_label_to_tag_mapping():
    assert LABEL_TO_TAG["Title"] == "H1"
    assert LABEL_TO_TAG["Section-header"] == "H2"
    assert LABEL_TO_TAG["Picture"] == "Figure"
    assert LABEL_TO_TAG["Page-header"] == "Artifact"


def test_resolve_layoutlm_model_dir_defaults_to_repo_folder():
    path = resolve_layoutlm_model_dir()
    assert path.name == "layoutLM_trained"
    assert path.parent == REPO_ROOT


def test_ensure_hf_model_layout_accepts_aliased_filenames():
    model_dir = REPO_ROOT / "layoutLM_trained"
    if not model_dir.is_dir():
        return

    canonical = ensure_hf_model_layout(model_dir)
    assert (canonical / "config.json").is_file()
    assert (canonical / "tokenizer.json").is_file()
    assert (canonical / "model.safetensors").is_file()


def test_parse_opendataloader_json_with_sample_lorem():
    sample_path = REPO_ROOT / "opendataloader-pdf-main" / "samples" / "json" / "lorem.json"
    if not sample_path.is_file():
        return

    data = json.loads(sample_path.read_text(encoding="utf-8"))
    layouts = DocumentLayoutAnalyzer.parse_opendataloader_json(
        data,
        page_sizes=[(595.0, 842.0)],
    )

    assert len(layouts) == 1
    assert layouts[0].page_number == 0
    assert [block.tag for block in layouts[0].blocks] == ["H1", "P"]
    assert layouts[0].blocks[0].text == "Lorem Ipsum"
    assert "Lorem ipsum dolor sit amet" in layouts[0].blocks[1].text


def test_parse_opendataloader_json_maps_types_and_normalizes_coordinates():
    fixture_path = FIXTURES_DIR / "opendataloader_blocks.json"
    data = json.loads(fixture_path.read_text(encoding="utf-8"))

    layouts = DocumentLayoutAnalyzer.parse_opendataloader_json(
        data,
        page_sizes=[(200.0, 400.0), (300.0, 600.0)],
    )

    assert len(layouts) == 2

    page_one_tags = [block.tag for block in layouts[0].blocks]
    assert page_one_tags == ["H3", "P", "L"]
    assert layouts[0].blocks[0].bbox == (100, 50, 900, 200)
    assert layouts[0].blocks[1].bbox == (100, 650, 900, 750)
    assert layouts[0].blocks[2].text == "North America Europe"

    page_two_tags = [block.tag for block in layouts[1].blocks]
    assert page_two_tags == ["Table", "Figure", "Caption", "Artifact", "Artifact"]
    assert layouts[1].blocks[0].text == "Region Revenue"
    assert layouts[1].blocks[0].bbox == (100, 166, 900, 583)
    assert layouts[1].blocks[3].page_number == 1


def test_parse_opendataloader_json_infers_likert_table_cells_from_paragraphs():
    data = {
        "number of pages": 1,
        "kids": [
            {
                "type": "paragraph",
                "page number": 1,
                "bounding box": [72.025, 179.454, 363.601, 214.023],
                "content": "Table 15 Improving Empirically Validated Assessment Tools (N = 99)",
            },
            {
                "type": "paragraph",
                "page number": 1,
                "bounding box": [234.6, 142.204, 283.068, 168.743],
                "content": "Definitely False",
            },
            {
                "type": "paragraph",
                "page number": 1,
                "bounding box": [297.63, 142.204, 338.358, 168.743],
                "content": "Possibly False",
            },
            {
                "type": "paragraph",
                "page number": 1,
                "bounding box": [360.65, 142.204, 449.398, 168.743],
                "content": "Not Sure Possibly True",
            },
            {
                "type": "paragraph",
                "page number": 1,
                "bounding box": [470.95, 142.204, 519.418, 168.743],
                "content": "Definitely True",
            },
            {
                "type": "paragraph",
                "page number": 1,
                "bounding box": [68.025, 91.179, 237.225, 130.973],
                "content": "I would need more explicit training in how to use and apply such techniques.",
            },
            {
                "type": "paragraph",
                "page number": 1,
                "bounding box": [240.6, 117.684, 501.946, 130.973],
                "content": "12.1% 11.1% 15.2% 40.4% 21.2%",
            },
        ],
    }

    layouts = DocumentLayoutAnalyzer.parse_opendataloader_json(
        data,
        page_sizes=[(612.0, 792.0)],
    )

    table_cells = [
        block
        for block in layouts[0].blocks
        if block.metadata.get("table_id") == "p1_table_15"
    ]

    assert [block.tag for block in table_cells] == [
        "TH",
        "TH",
        "TH",
        "TH",
        "TH",
        "TH",
        "TH",
        "TD",
        "TD",
        "TD",
        "TD",
        "TD",
    ]
    assert [block.text for block in table_cells[:6]] == [
        "Statement",
        "Definitely False",
        "Possibly False",
        "Not Sure",
        "Possibly True",
        "Definitely True",
    ]
    assert table_cells[6].text == "I would need more explicit training in how to use and apply such techniques."
    assert [block.text for block in table_cells[7:]] == ["12.1%", "11.1%", "15.2%", "40.4%", "21.2%"]
    assert table_cells[6].metadata["table_row"] == 1
    assert table_cells[6].metadata["table_col"] == 0
    assert table_cells[7].metadata["table_col"] == 1


def test_auto_tag_pdf_passes_table_cell_metadata_to_cpp(monkeypatch, tmp_path):
    mock_layouts = [
        PageLayout(
            page_number=0,
            width=612,
            height=792,
            blocks=[
                StructureBlock(
                    tag="TH",
                    bbox=(100, 100, 200, 200),
                    page_number=0,
                    content="Statement",
                    metadata={
                        "raw_bbox": [10.0, 20.0, 30.0, 40.0],
                        "table_id": "p1_table_1",
                        "table_row": 0,
                        "table_col": 0,
                        "table_header": True,
                    },
                )
            ],
        )
    ]

    def fake_analyze(self, path):
        return mock_layouts

    captured_blocks = []

    def fake_run(cmd, **kwargs):
        captured_blocks.extend(json.loads(Path(cmd[2]).read_text(encoding="utf-8")))
        shutil.copy2(cmd[1], cmd[-1])
        import subprocess

        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(
        "backend.opendataloader_layout.OpenDataLoaderLayoutAnalyzer.analyze_document",
        fake_analyze,
    )
    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr("backend.pdf_auto_tagging.HAS_PIKEPDF", True)
    monkeypatch.setattr("backend.pdf_auto_tagging._has_structure_tree", lambda _: False)

    source_path = tmp_path / "source.pdf"
    output_path = tmp_path / "output.pdf"
    make_minimal_pdf(source_path)

    result = auto_tag_pdf(source_path, output_path=output_path, overwrite_tags=True)

    assert result["success"] is True
    assert captured_blocks == [
        {
            "page": 0,
            "tag": "TH",
            "bbox": [10.0, 20.0, 30.0, 40.0],
            "table_id": "p1_table_1",
            "table_row": 0,
            "table_col": 0,
            "table_header": True,
        }
    ]


def test_auto_tag_pdf_passes_artifact_blocks_to_cpp(monkeypatch, tmp_path):
    mock_layouts = [
        PageLayout(
            page_number=0,
            width=612,
            height=792,
            blocks=[
                StructureBlock(
                    tag="Artifact",
                    bbox=(60, 744, 550, 760),
                    page_number=0,
                    content="Running header",
                    metadata={"raw_bbox": [60.0, 744.0, 550.0, 760.0]},
                )
            ],
        )
    ]

    def fake_analyze(self, path):
        return mock_layouts

    captured_blocks = []

    def fake_run(cmd, **kwargs):
        captured_blocks.extend(json.loads(Path(cmd[2]).read_text(encoding="utf-8")))
        shutil.copy2(cmd[1], cmd[-1])
        import subprocess

        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(
        "backend.opendataloader_layout.OpenDataLoaderLayoutAnalyzer.analyze_document",
        fake_analyze,
    )
    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr("backend.pdf_auto_tagging.HAS_PIKEPDF", True)
    monkeypatch.setattr("backend.pdf_auto_tagging._has_structure_tree", lambda _: False)

    source_path = tmp_path / "source.pdf"
    output_path = tmp_path / "output.pdf"
    make_minimal_pdf(source_path)

    result = auto_tag_pdf(source_path, output_path=output_path, overwrite_tags=True)

    assert result["success"] is True
    assert captured_blocks == [
        {
            "page": 0,
            "tag": "Artifact",
            "bbox": [60.0, 744.0, 550.0, 760.0],
        }
    ]


def test_auto_tag_pdf_reports_errors_on_failure(monkeypatch, tmp_path):
    def failing_analyze(self, path):
        raise RuntimeError("Layout analyzer failed")

    monkeypatch.setattr(
        "backend.opendataloader_layout.OpenDataLoaderLayoutAnalyzer.analyze_document",
        failing_analyze
    )

    monkeypatch.setattr("backend.pdf_auto_tagging._has_structure_tree", lambda _: False)

    source_path = tmp_path / "source.pdf"
    source_path.touch()

    result = auto_tag_pdf(source_path)

    assert result["success"] is False
    assert "Layout analyzer failed" in result["error"]


def test_auto_tag_pdf_skips_existing_tags_without_overwrite(monkeypatch, tmp_path):
    monkeypatch.setattr("backend.pdf_auto_tagging.HAS_PIKEPDF", True)
    monkeypatch.setattr("backend.pdf_auto_tagging._has_structure_tree", lambda _: True)

    def should_not_run(self, path):
        raise AssertionError("Layout analyzer should not run when skipping")

    monkeypatch.setattr(
        "backend.opendataloader_layout.OpenDataLoaderLayoutAnalyzer.analyze_document",
        should_not_run
    )

    result = auto_tag_pdf(tmp_path / "source.pdf", overwrite_tags=False)

    assert result["success"] is True
    assert result["skipped"] is True
    assert result["tags_created"] == 0


def test_auto_tag_pdf_runs_builder_with_overwrite(monkeypatch, tmp_path):
    from backend.layout_model import PageLayout, StructureBlock
    
    mock_layouts = [
        PageLayout(
            page_number=0,
            width=200,
            height=400,
            blocks=[
                StructureBlock(
                    tag="P",
                    bbox=(100, 100, 200, 200),
                    page_number=0,
                    content="Hello",
                    metadata={"raw_bbox": [10.0, 20.0, 30.0, 40.0]}
                )
            ],
        )
    ]

    def fake_analyze(self, path):
        return mock_layouts

    called_subprocess = []
    def fake_run(cmd, **kwargs):
        called_subprocess.append(cmd)
        shutil.copy2(cmd[1], cmd[-1])
        import subprocess
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(
        "backend.opendataloader_layout.OpenDataLoaderLayoutAnalyzer.analyze_document",
        fake_analyze
    )
    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr("backend.pdf_auto_tagging.HAS_PIKEPDF", True)
    monkeypatch.setattr("backend.pdf_auto_tagging._has_structure_tree", lambda _: True)

    source_path = tmp_path / "source.pdf"
    output_path = tmp_path / "output.pdf"
    make_minimal_pdf(source_path)

    result = auto_tag_pdf(source_path, output_path=output_path, overwrite_tags=True)

    assert result["success"] is True
    assert result["tags_created"] == 1
    assert len(called_subprocess) == 1
    assert called_subprocess[0][1] == str(source_path)
    assert called_subprocess[0][3] == str(output_path)


def test_auto_tag_pdf_normalizes_language_metadata_after_tagging(monkeypatch, tmp_path):
    mock_layouts = [
        PageLayout(
            page_number=0,
            width=72,
            height=72,
            blocks=[],
        )
    ]

    def fake_analyze(self, path):
        return mock_layouts

    def fake_run(cmd, **kwargs):
        shutil.copy2(cmd[1], cmd[-1])
        import subprocess

        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(
        "backend.opendataloader_layout.OpenDataLoaderLayoutAnalyzer.analyze_document",
        fake_analyze,
    )
    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr("backend.pdf_auto_tagging.HAS_PIKEPDF", True)
    monkeypatch.setattr("backend.pdf_auto_tagging._has_structure_tree", lambda _: False)

    source_path = tmp_path / "source.pdf"
    output_path = tmp_path / "output.pdf"
    make_minimal_pdf(source_path, language="English")

    result = auto_tag_pdf(source_path, output_path=output_path, overwrite_tags=True)

    assert result["success"] is True
    with pikepdf.open(output_path) as pdf:
        assert str(pdf.Root.Lang) == "en-US"
        with pdf.open_metadata() as meta:
            assert meta["dc:language"] == ["en-US"]


def test_overlay_labels_use_tag_and_text_only():
    block = StructureBlock(tag="P", page_number=0, content="A short paragraph for preview text.")

    label = build_block_label(block)

    assert label == "P  A short paragraph for preview text."
    assert "%" not in label
