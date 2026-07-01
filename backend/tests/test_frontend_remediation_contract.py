from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_frontend_does_not_offer_structure_rebuild_opt_out():
    panel_source = (
        REPO_ROOT / "frontend/src/components/RemediationPanel.tsx"
    ).read_text(encoding="utf-8")
    api_source = (REPO_ROOT / "frontend/src/api.ts").read_text(encoding="utf-8")
    types_source = (REPO_ROOT / "frontend/src/types.ts").read_text(encoding="utf-8")

    assert "Rebuild structure with OpenDataLoader" not in panel_source
    assert "overwriteTags" not in panel_source
    assert "overwrite_tags" not in api_source
    assert "overwrite_tags" not in types_source


def test_frontend_offers_remediation_report_download_after_remediation():
    panel_source = (
        REPO_ROOT / "frontend/src/components/RemediationPanel.tsx"
    ).read_text(encoding="utf-8")
    api_source = (REPO_ROOT / "frontend/src/api.ts").read_text(encoding="utf-8")

    assert "getRemediationReportURL" in api_source
    assert "`${API_BASE}/remediate/report/${reportId}`" in api_source
    assert "getRemediationReportURL(report.id)" in panel_source
    assert "Download Remediation Report" in panel_source
    assert "flex-wrap" in panel_source
    assert "const [remediationReportAvailable, setRemediationReportAvailable]" in panel_source
    assert "useState(false)" in panel_source
    assert (
        "setRemediationReportAvailable(Boolean(response.remediation_report_filename))"
        in panel_source
    )
    assert "{remediationReportAvailable && (" in panel_source
    assert "{!remediationReportAvailable && (" in panel_source
    assert 'role="status"' in panel_source
    assert (
        "Remediation succeeded, but the remediation report could not be generated or downloaded."
        in panel_source
    )
