from pathlib import Path

import pdfplumber
import pytest

from backend.remediation_report import generate_remediation_report_for_api


def generate_report_with_unicode_details(tmp_path: Path, details: dict) -> Path:
    return generate_remediation_report_for_api(
        original_filename="source.pdf",
        file_id="file-1",
        report_id="report-1",
        file_type="pdf",
        analysis_report={"all_issues": []},
        remediation_results=[
            {
                "issue_id": "pdf-unicode-mapping",
                "success": True,
                "message": "Unicode mapping result",
                "details": details,
            }
        ],
        remediated_file_path="output.pdf",
        output_dir=tmp_path,
    )


def extract_pdf_text(path: Path) -> str:
    with pdfplumber.open(path) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


def test_api_report_is_readable_pdf_with_remediation_sections(tmp_path: Path) -> None:
    path = generate_remediation_report_for_api(
        original_filename="accessible-source.pdf",
        file_id="file-123",
        report_id="report-456",
        file_type="pdf",
        analysis_report={
            "all_issues": [
                {
                    "id": "manual-1",
                    "rule_id": "pdf-alt-text",
                    "rule_name": "Image Alternative Text",
                    "severity": "serious",
                    "message": "Image is missing alternative text",
                    "fix_suggestion": "Add concise alternative text manually",
                    "automatable_fix": False,
                }
            ]
        },
        remediation_results=[
            {
                "issue_id": "fixed-1",
                "success": True,
                "message": "Document language was set successfully",
                "original_value": "unset",
                "new_value": "en-US",
            },
            {
                "issue_id": "failed-1",
                "success": False,
                "message": "Could not create a bookmark hierarchy",
            },
        ],
        remediated_file_path="output.pdf",
        output_dir=tmp_path,
    )

    assert path.suffix == ".pdf"
    assert path.name.startswith("Remediation_Report_report-456_")
    assert path.read_bytes().startswith(b"%PDF")

    text = extract_pdf_text(path)
    assert "PDFAccess Remediation Report" in text
    assert "accessible-source.pdf" in text
    assert "Successful Fixes" in text
    assert "Document language was set successfully" in text
    assert "Previous value: unset" in text
    assert "Failed Fixes" in text
    assert "Could not create a bookmark hierarchy" in text
    assert "Remaining Manual Work" in text
    assert "Add concise alternative text manually" in text


def test_api_report_preserves_multilingual_dynamic_text(tmp_path: Path) -> None:
    path = generate_remediation_report_for_api(
        original_filename="中文报告.pdf",
        file_id="文件-1",
        report_id="报告-1",
        file_type="pdf",
        analysis_report={"all_issues": []},
        remediation_results=[
            {
                "issue_id": "语言-1",
                "success": True,
                "message": "修复成功：中文内容已保留",
            }
        ],
        remediated_file_path="输出.pdf",
        output_dir=tmp_path,
    )

    text = extract_pdf_text(path)
    assert "中文报告.pdf" in text
    assert "文件-1" in text
    assert "修复成功：中文内容已保留" in text


def test_api_report_treats_hostile_markup_as_literal_text(tmp_path: Path) -> None:
    hostile = "Literal <b>bold</b> <font>color</font> & &copy;"
    path = generate_remediation_report_for_api(
        original_filename="markup.pdf",
        file_id="file-1",
        report_id="report-1",
        file_type="pdf",
        analysis_report={"all_issues": []},
        remediation_results=[
            {
                "issue_id": "markup-1",
                "success": True,
                "message": hostile,
            }
        ],
        remediated_file_path=None,
        output_dir=tmp_path,
    )

    text = extract_pdf_text(path)
    assert hostile in text


@pytest.mark.parametrize(
    "details,expected",
    [
        (
            {"llm_invoked": False, "llm_recommendation_applied": False},
            "was not used",
        ),
        (
            {
                "llm_invoked": True,
                "llm_recommendation_applied": True,
                "evaluated": 1,
                "applied": 1,
            },
            "1 recommendation(s) were applied",
        ),
        (
            {
                "llm_invoked": True,
                "llm_recommendation_applied": False,
                "evaluated": 1,
                "applied": 0,
            },
            "0 recommendation(s) were applied",
        ),
        (
            {
                "llm_invoked": False,
                "llm_recommendation_applied": False,
                "llm_unavailable": True,
            },
            "requested but unavailable",
        ),
    ],
)
def test_report_contains_llm_disclosure(
    details: dict, expected: str, tmp_path: Path
) -> None:
    path = generate_report_with_unicode_details(tmp_path, details)

    assert expected in extract_pdf_text(path)


def test_report_includes_gemini_response_details(tmp_path: Path) -> None:
    details = {
        "provider": "Gemini",
        "llm_invoked": True,
        "llm_recommendation_applied": False,
        "evaluated": 1,
        "applied": 0,
        "model": "gemini-3.1-flash-lite",
        "min_confidence": 0.98,
        "max_occurrences": 3,
        "decisions": [
            {
                "font": "/CIDFont+F6",
                "cid": 2870,
                "pages": [30, 171],
                "occurrence_count": 12,
                "resolution_source": "gemini-3.1-flash-lite",
                "llm_model_used": "gemini-3.1-flash-lite",
                "llm_invoked": True,
                "llm_recommendation_applied": False,
                "confidence": 0.91,
                "rejection_reason": "confidence-below-threshold",
                "unresolved_reason": "confidence-below-threshold",
                "llm_context": {
                    "document_title": "dissertation.pdf",
                    "font": "/CIDFont+F6",
                    "cid": 2870,
                    "gid": 2870,
                    "glyph_name": "two.superior",
                    "candidates": ["U+0032", "U+00B2"],
                    "deterministic_contradictions": ["2", "²"],
                    "sampled_pages": [30, 171],
                    "image_evidence_count": 4,
                    "occurrences": [
                        {
                            "page": 30,
                            "position": "superscript",
                            "font_size": 6.5,
                            "baseline_y": 412.3,
                            "masked_line": "factor the following polynomial: x[UNKNOWN] - 2x - 3",
                            "paragraph": "For example, if a question says...",
                        }
                    ],
                },
                "llm_response": {
                    "status": "verified",
                    "unicode_sequence": ["U+0032"],
                    "rendered_text": "2",
                    "confidence": 0.91,
                    "occurrences_consistent": True,
                    "alternatives": ["U+00B2"],
                    "evidence": [
                        "Glyph appears raised relative to baseline in all samples.",
                        "Surrounding math uses x squared notation.",
                    ],
                    "reason": "Superscript styling of digit two in polynomial expression.",
                    "vision_probe": "A1B2C3",
                },
            }
        ],
    }
    path = generate_report_with_unicode_details(tmp_path, details)
    text = extract_pdf_text(path)

    assert "Gemini Unicode Mapping Review" in text
    assert "Minimum confidence threshold" in text
    assert "0.98" in text
    assert "Glyph decision 1: /CIDFont+F6 / CID 2870" in text
    assert "Evidence sent to Gemini" in text
    assert "U+0032" in text
    assert "U+00B2" in text
    assert "confidence-below-threshold" in text
    assert "Gemini response" in text
    assert "DeepSeek" not in text
    assert "Superscript styling of digit two" in text
    assert "Raw JSON response" in text
    assert "vision_probe" in text
    assert "Masked line" in text
    assert "superscript" in text


def test_report_includes_gemini_api_error_details(tmp_path: Path) -> None:
    details = {
        "provider": "Gemini",
        "llm_invoked": True,
        "llm_recommendation_applied": False,
        "evaluated": 1,
        "applied": 0,
        "model": "gemini-3.1-flash-lite",
        "decisions": [
            {
                "font": "/CIDFont+F6",
                "cid": 2870,
                "pages": [30],
                "occurrence_count": 58,
                "resolution_source": "gemini-3.1-flash-lite",
                "llm_invoked": True,
                "llm_recommendation_applied": False,
                "llm_model_used": "gemini-3.1-flash-lite",
                "unresolved_reason": "api-status-400",
                "llm_response": {
                    "api_error": {
                        "status_code": 400,
                        "model": "gemini-3.1-flash-lite",
                        "body": {"error": {"message": "vision not supported"}},
                    }
                },
            }
        ],
    }
    path = generate_report_with_unicode_details(tmp_path, details)
    text = extract_pdf_text(path)

    assert "Gemini API error" in text
    assert "vision not supported" in text
    assert "HTTP status" in text


def test_report_includes_jev_glyph_consensus_details(tmp_path: Path) -> None:
    details = {
        "provider": "Gemini",
        "provider_label": "Gemini 3.1 Flash-Lite with Jev consensus",
        "llm_invoked": True,
        "llm_recommendation_applied": True,
        "evaluated": 1,
        "applied": 1,
        "model": "gemini-3.1-flash-lite",
        "jev_consensus_enabled": True,
        "jev_consensus_model": "typesafe-ai/jev",
        "jev_consensus_min_confidence": 0.98,
        "jev_consensus_accepted": 1,
        "jev_consensus_gateway": "vercel-ai-gateway",
        "decisions": [
            {
                "font": "/CIDFont+F6",
                "cid": 2870,
                "llm_invoked": True,
                "llm_recommendation_applied": True,
                "unicode_text": "2",
                "jev_consensus": {
                    "accepted": True,
                    "confidence": 0.99,
                    "rejection_reason": None,
                    "model_requested": "typesafe-ai/jev",
                    "model_used": "jev-1.13.0",
                    "selected_candidate": "Unicode U+0032, rendered as 2",
                    "expected_candidate": "Unicode U+0032, rendered as 2",
                    "input_tokens": 211,
                    "output_tokens": 8,
                    "gateway": "vercel-ai-gateway",
                    "response": {
                        "model": "jev-1.13.0",
                        "answers": {
                            "unicode_consensus": {
                                "type": "choice",
                                "choice": "candidate_0",
                                "confidence": 0.99,
                            }
                        },
                    },
                },
            }
        ],
    }

    path = generate_report_with_unicode_details(tmp_path, details)
    text = extract_pdf_text(path)

    assert "Jev glyph consensus enabled" in text
    assert "Jev glyph consensus via Vercel AI Gateway" in text
    assert "jev-1.13.0" in text
    assert "Expected visual candidate" in text
    assert "Raw Jev response" in text


def test_report_skips_empty_gemini_response_table(tmp_path: Path) -> None:
    details = {
        "provider": "Gemini",
        "llm_invoked": True,
        "evaluated": 1,
        "applied": 0,
        "model": "gemini-3.1-flash-lite",
        "decisions": [
            {
                "font": "/CIDFont+F6",
                "cid": 2870,
                "pages": [30],
                "occurrence_count": 1,
                "resolution_source": "gemini-3.1-flash-lite",
                "llm_invoked": True,
                "llm_recommendation_applied": False,
                "llm_response": {},
            }
        ],
    }
    path = generate_report_with_unicode_details(tmp_path, details)
    assert path.read_bytes().startswith(b"%PDF")


def test_report_discloses_jev_structure_refinement(tmp_path: Path) -> None:
    path = generate_remediation_report_for_api(
        original_filename="source.pdf",
        file_id="file-1",
        report_id="report-jev",
        file_type="pdf",
        analysis_report={"all_issues": []},
        remediation_results=[
            {
                "issue_id": "pdf-auto-tag",
                "success": True,
                "message": "Document structure rebuilt",
                "details": {
                    "jev_refinement": {
                        "enabled": True,
                        "attempted_blocks": 18,
                        "applied_blocks": 3,
                        "retained_blocks": 15,
                        "model_requested": "typesafe-ai/jev",
                        "models_used": ["typesafe-ai/jev"],
                        "gateway": "vercel-ai-gateway",
                        "min_confidence": 0.90,
                        "input_tokens": 1200,
                        "output_tokens": 220,
                        "errors": [],
                    }
                },
            }
        ],
        remediated_file_path="output.pdf",
        output_dir=tmp_path,
    )

    text = extract_pdf_text(path)
    assert "TypeSafe Jev through Vercel AI Gateway evaluated 18" in text
    assert "Jev Structure Review via Vercel AI Gateway" in text
    assert "typesafe-ai/jev" in text
    assert "vercel-ai-gateway" in text
    assert "Tag refinements applied" in text
    assert "3" in text
