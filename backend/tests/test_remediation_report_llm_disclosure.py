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
    assert "PDF Accessibility Remediation Report" in text
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
