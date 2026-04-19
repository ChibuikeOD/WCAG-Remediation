"""
Tests for the OpenDataLoader-backed PDF auto-tagging flow.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.layout_model import DocumentLayoutAnalyzer, PageLayout, StructureBlock
from backend.pdf_auto_tagging import auto_tag_pdf
from backend.pdf_overlay_debug import build_block_label
from backend.pdf_structure_builder import TaggingResult


FIXTURES_DIR = Path(__file__).parent / "fixtures"
REPO_ROOT = Path(__file__).parent.parent.parent


def test_parse_opendataloader_json_with_sample_lorem():
    sample_path = REPO_ROOT / "opendataloader-pdf-main" / "samples" / "json" / "lorem.json"
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


def test_auto_tag_pdf_reports_runtime_setup_errors(monkeypatch, tmp_path):
    class FailingAnalyzer:
        def _ensure_runtime(self):
            raise RuntimeError("OpenDataLoader runtime not available")

    monkeypatch.setattr("backend.pdf_auto_tagging.DocumentLayoutAnalyzer", FailingAnalyzer)

    result = auto_tag_pdf(tmp_path / "source.pdf")

    assert result["success"] is False
    assert "OpenDataLoader runtime not available" in result["error"]


def test_auto_tag_pdf_skips_existing_tags_without_overwrite(monkeypatch, tmp_path):
    class Analyzer:
        def _ensure_runtime(self):
            return None

    monkeypatch.setattr("backend.pdf_auto_tagging.DocumentLayoutAnalyzer", Analyzer)
    monkeypatch.setattr("backend.pdf_auto_tagging.HAS_PIKEPDF", True)
    monkeypatch.setattr("backend.pdf_auto_tagging._has_structure_tree", lambda _: True)

    result = auto_tag_pdf(tmp_path / "source.pdf", overwrite_tags=False)

    assert result["success"] is True
    assert result["skipped"] is True
    assert result["tags_created"] == 0


def test_auto_tag_pdf_runs_builder_with_overwrite(monkeypatch, tmp_path):
    called = {}
    layouts = [PageLayout(page_number=0, width=200, height=400, blocks=[StructureBlock(tag="P", page_number=0, content="Hello")])]

    class Analyzer:
        def _ensure_runtime(self):
            return None

        def analyze_document(self, source_path):
            called["analyze_document"] = source_path
            return layouts

    class Builder:
        def build_tagged_pdf(self, source_path, output_path, incoming_layouts, overwrite_existing_tags=False):
            called["build"] = {
                "source_path": source_path,
                "output_path": output_path,
                "layouts": incoming_layouts,
                "overwrite_existing_tags": overwrite_existing_tags,
            }
            return TaggingResult(
                success=True,
                output_path=output_path,
                total_pages=1,
                total_tags_created=1,
                tag_counts={"P": 1},
            )

    monkeypatch.setattr("backend.pdf_auto_tagging.DocumentLayoutAnalyzer", Analyzer)
    monkeypatch.setattr("backend.pdf_auto_tagging.PDFStructureBuilder", Builder)
    monkeypatch.setattr("backend.pdf_auto_tagging.HAS_PIKEPDF", True)
    monkeypatch.setattr("backend.pdf_auto_tagging._has_structure_tree", lambda _: True)

    source_path = tmp_path / "source.pdf"
    output_path = tmp_path / "output.pdf"
    result = auto_tag_pdf(source_path, output_path=output_path, overwrite_tags=True)

    assert result["success"] is True
    assert result["tags_created"] == 1
    assert called["build"]["overwrite_existing_tags"] is True
    assert called["build"]["layouts"] == layouts
    assert called["build"]["source_path"] == source_path
    assert called["build"]["output_path"] == output_path


def test_overlay_labels_use_tag_and_text_only():
    block = StructureBlock(tag="P", page_number=0, content="A short paragraph for preview text.")

    label = build_block_label(block)

    assert label == "P  A short paragraph for preview text."
    assert "%" not in label
