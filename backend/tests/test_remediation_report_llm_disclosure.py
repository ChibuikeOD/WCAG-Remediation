import json
from pathlib import Path

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

    report = json.loads(path.read_text(encoding="utf-8"))

    assert expected in report["summary"]["llm_disclosure"]
