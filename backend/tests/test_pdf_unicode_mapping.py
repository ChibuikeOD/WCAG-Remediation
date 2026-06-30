from pathlib import Path

import pikepdf
import pytest

from backend.deepseek_unicode_verifier import DeepSeekDecision
import backend.pdf_unicode_mapping as unicode_module
from backend.pdf_unicode_mapping import (
    DeterministicResolution,
    FontEvidence,
    ParsedToUnicode,
    add_cmap_mappings,
    build_ambiguity_context,
    collect_font_evidence,
    inventory_missing_unicode,
    parse_to_unicode_cmap,
    repair_missing_unicode,
    resolve_deterministically,
    verify_repair,
)


SAMPLE_CMAP = b"""/CIDInit /ProcSet findresource begin
12 dict begin begincmap
/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def
/CMapName /Adobe-Identity-UCS def
/CMapType 2 def
1 begincodespacerange
<0000> <FFFF>
endcodespacerange
1 beginbfchar
<0374> <0032>
endbfchar
endcmap CMapName currentdict /CMap defineresource pop end end
"""


def build_type0_pdf(path: Path, shown_cid: int) -> Path:
    with pikepdf.Pdf.new() as pdf:
        page = pdf.add_blank_page(page_size=(72, 72))
        descriptor = pdf.make_indirect(
            pikepdf.Dictionary(
                Type=pikepdf.Name("/FontDescriptor"),
                FontName=pikepdf.Name("/TestFont"),
                Flags=4,
                FontBBox=pikepdf.Array([0, 0, 1000, 1000]),
                ItalicAngle=0,
                Ascent=800,
                Descent=-200,
                CapHeight=700,
                StemV=80,
            )
        )
        descendant = pdf.make_indirect(
            pikepdf.Dictionary(
                Type=pikepdf.Name("/Font"),
                Subtype=pikepdf.Name("/CIDFontType2"),
                BaseFont=pikepdf.Name("/TestFont"),
                CIDSystemInfo=pikepdf.Dictionary(
                    Registry="Adobe", Ordering="Identity", Supplement=0
                ),
                CIDToGIDMap=pikepdf.Name("/Identity"),
                FontDescriptor=descriptor,
            )
        )
        font = pdf.make_indirect(
            pikepdf.Dictionary(
                Type=pikepdf.Name("/Font"),
                Subtype=pikepdf.Name("/Type0"),
                BaseFont=pikepdf.Name("/TestFont"),
                Encoding=pikepdf.Name("/Identity-H"),
                DescendantFonts=pikepdf.Array([descendant]),
                ToUnicode=pdf.make_stream(SAMPLE_CMAP),
            )
        )
        page.Resources = pikepdf.Dictionary(
            Font=pikepdf.Dictionary(F1=font)
        )
        page.Contents = pdf.make_stream(
            f"BT /F1 12 Tf 10 50 Td <{shown_cid:04X}> Tj ET".encode("ascii")
        )
        pdf.save(path)
    return path


def test_inventory_finds_used_cid_missing_from_tounicode(tmp_path: Path) -> None:
    path = build_type0_pdf(tmp_path / "missing.pdf", shown_cid=0x0B36)

    findings = inventory_missing_unicode(path)

    assert len(findings) == 1
    finding = findings[0]
    assert finding.cid == 0x0B36
    assert finding.occurrence_count == 1
    assert finding.pages == (1,)


def test_inventory_ignores_mapped_cid(tmp_path: Path) -> None:
    path = build_type0_pdf(tmp_path / "mapped.pdf", shown_cid=0x0374)

    assert inventory_missing_unicode(path) == []


def test_cmap_round_trip_preserves_existing_entries() -> None:
    parsed = parse_to_unicode_cmap(SAMPLE_CMAP)

    updated = add_cmap_mappings(SAMPLE_CMAP, {0x0B36: "2"})
    reparsed = parse_to_unicode_cmap(updated)

    assert parsed.code_width == 2
    assert reparsed.mappings[0x0374] == "2"
    assert reparsed.mappings[0x0B36] == "2"


def test_unique_gid_mapping_resolves_without_llm(tmp_path: Path) -> None:
    finding = inventory_missing_unicode(
        build_type0_pdf(tmp_path / "unique.pdf", shown_cid=0x0B36)
    )[0]
    evidence = FontEvidence(
        unicode_by_gid={2870: ("2",)},
        glyph_name_by_gid={},
        unicode_by_glyph_name={},
    )

    result = resolve_deterministically(finding, evidence)

    assert result == DeterministicResolution(text="2", evidence=("font-cmap",))


def test_conflicting_font_evidence_stays_ambiguous(tmp_path: Path) -> None:
    finding = inventory_missing_unicode(
        build_type0_pdf(tmp_path / "conflict.pdf", shown_cid=0x0B36)
    )[0]
    evidence = FontEvidence(
        unicode_by_gid={2870: ("2",)},
        glyph_name_by_gid={2870: "two.superior"},
        unicode_by_glyph_name={"two.superior": "²"},
    )

    assert resolve_deterministically(finding, evidence) is None


LOCAL_DISSERTATION = (
    Path(__file__).parents[4]
    / "Check PDFs"
    / "Duseau K.L. CAS PhD Dissertation 2025.pdf"
)


@pytest.mark.skipif(
    not LOCAL_DISSERTATION.exists(), reason="local dissertation fixture is unavailable"
)
def test_dissertation_ambiguous_glyph_gets_visual_and_text_context() -> None:
    finding = next(
        item
        for item in inventory_missing_unicode(LOCAL_DISSERTATION)
        if item.cid == 2870
    )

    evidence = collect_font_evidence(LOCAL_DISSERTATION, finding)
    context = build_ambiguity_context(
        LOCAL_DISSERTATION, finding, evidence, max_occurrences=2
    )

    assert resolve_deterministically(finding, evidence) is None
    assert len(context["occurrences"]) == 2
    assert len(context["images"]) == 3
    assert len({item["page"] for item in context["occurrences"]}) == 2
    assert all("[UNKNOWN]" in item["masked_line"] for item in context["occurrences"])
    assert all(
        item["position"] in {"superscript", "subscript", "baseline"}
        for item in context["occurrences"]
    )


class VerifierSpy:
    def __init__(self, decision: DeepSeekDecision) -> None:
        self.decision = decision
        self.calls: list[dict] = []

    def __call__(self, context: dict) -> DeepSeekDecision:
        self.calls.append(context)
        return self.decision


def accepted_decision(text: str = "2") -> DeepSeekDecision:
    return DeepSeekDecision(
        accepted=True,
        text=text,
        confidence=0.99,
        rejection_reason=None,
        response={"status": "verified"},
    )


def rejected_decision(reason: str) -> DeepSeekDecision:
    return DeepSeekDecision(
        accepted=False,
        text=None,
        confidence=0.99,
        rejection_reason=reason,
        response={"status": "ambiguous"},
    )


def read_font_cmap(path: Path) -> ParsedToUnicode:
    with pikepdf.open(path) as pdf:
        font = pdf.pages[0].Resources.Font.F1
        return parse_to_unicode_cmap(font.ToUnicode.read_bytes())


def test_complete_document_skips_llm(tmp_path: Path) -> None:
    path = build_type0_pdf(tmp_path / "complete.pdf", shown_cid=0x0374)
    verifier = VerifierSpy(accepted_decision())

    result = repair_missing_unicode(path, verifier=verifier)

    assert verifier.calls == []
    assert result["details"]["llm_invoked"] is False


def test_ambiguous_accepted_decision_updates_cmap(tmp_path: Path, monkeypatch) -> None:
    path = build_type0_pdf(tmp_path / "ambiguous.pdf", shown_cid=0x0B36)
    verifier = VerifierSpy(accepted_decision("2"))
    monkeypatch.setattr(unicode_module, "verify_repair", lambda *_args: (True, "ok"))

    result = repair_missing_unicode(path, verifier=verifier)

    assert read_font_cmap(path).mappings[0x0B36] == "2"
    assert result["details"]["llm_invoked"] is True
    assert result["details"]["llm_recommendation_applied"] is True


def test_rejected_decision_does_not_change_pdf(tmp_path: Path) -> None:
    path = build_type0_pdf(tmp_path / "rejected.pdf", shown_cid=0x0B36)
    before = path.read_bytes()

    result = repair_missing_unicode(
        path, verifier=VerifierSpy(rejected_decision("occurrence-conflict"))
    )

    assert path.read_bytes() == before
    assert result["details"]["llm_invoked"] is True
    assert result["details"]["llm_recommendation_applied"] is False


def test_failed_post_write_verification_rolls_back(tmp_path: Path, monkeypatch) -> None:
    path = build_type0_pdf(tmp_path / "rollback.pdf", shown_cid=0x0B36)
    before = path.read_bytes()
    monkeypatch.setattr(
        unicode_module, "verify_repair", lambda *_args: (False, "visual-diff")
    )

    result = repair_missing_unicode(
        path, verifier=VerifierSpy(accepted_decision("2"))
    )

    assert path.read_bytes() == before
    assert result["success"] is False
    assert result["details"]["rollback_reason"] == "visual-diff"
    assert result["details"]["llm_recommendation_applied"] is False
    assert "0 recommendation(s) were applied" in result["message"]


def test_verify_repair_rejects_qpdf_failure(tmp_path: Path, monkeypatch) -> None:
    original = build_type0_pdf(tmp_path / "original.pdf", shown_cid=0x0374)
    candidate = tmp_path / "candidate.pdf"
    candidate.write_bytes(original.read_bytes())
    monkeypatch.setattr(
        unicode_module,
        "_qpdf_check",
        lambda _path: (False, "qpdf-check-failed"),
        raising=False,
    )

    verified, reason = verify_repair(original, candidate, [], set())

    assert verified is False
    assert reason == "qpdf-check-failed"
